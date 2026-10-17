import asyncio
import re
import time
import uuid

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import hint, title
from .base import PluginContext, PluginSpec

KEY = "pending"
TICK = 15
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
DURATION_RE = re.compile(r"^(\d+)\s*([smhd])\s+(.+)$", re.IGNORECASE | re.DOTALL)


def parse(text: str) -> tuple[int, str] | None:
    match = DURATION_RE.match(text.strip())
    if not match:
        return None
    seconds = int(match.group(1)) * UNITS[match.group(2).lower()]
    return seconds, match.group(3).strip()


def build(ctx: PluginContext) -> Router:
    router = Router(name="reminders")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Напоминания", "⏰")
            + "\nФормат: <code>/remind 10m выпить воду</code>\n"
            "Единицы: s — секунды, m — минуты, h — часы, d — дни.\n"
            + hint("Напоминания сохраняются и переживают перезапуск бота.")
        )

    @router.message(Command("remind"))
    async def cmd_remind(message: Message, command: CommandObject) -> None:
        parsed = parse(command.args or "")
        if not parsed:
            await message.answer("Пример: <code>/remind 30m позвонить маме</code>")
            return
        seconds, text = parsed
        if seconds > 365 * 86400:
            await message.answer("Максимум — год.")
            return
        pending = ctx.get(KEY, [])
        pending.append({
            "id": uuid.uuid4().hex[:8],
            "chat_id": message.chat.id,
            "at": int(time.time()) + seconds,
            "text": text[:500],
        })
        ctx.set(KEY, pending)
        await message.answer(f"⏰ Напомню через {seconds} с: {text[:200]}")

    @router.message(Command("reminders"))
    async def cmd_list(message: Message) -> None:
        mine = [r for r in ctx.get(KEY, []) if r["chat_id"] == message.chat.id]
        if not mine:
            await message.answer("Активных напоминаний нет.")
            return
        lines = [f"• {time.strftime('%d.%m %H:%M', time.localtime(r['at']))} — {r['text']}" for r in mine]
        await message.answer(title("Активные", "⏰") + "\n" + "\n".join(lines))

    return router


async def background(bot: Bot, ctx: PluginContext) -> None:
    while True:
        await asyncio.sleep(TICK)
        now = time.time()
        due = [r for r in ctx.get(KEY, []) if r["at"] <= now]
        if not due:
            continue
        for reminder in due:
            try:
                await bot.send_message(reminder["chat_id"], f"⏰ <b>Напоминание</b>\n{reminder['text']}")
            except Exception:
                pass
        sent_ids = {r["id"] for r in due}
        ctx.set(KEY, [r for r in ctx.get(KEY, []) if r["id"] not in sent_ids])


SPEC = PluginSpec(
    name="reminders",
    title="Напоминания",
    icon="⏰",
    description="Напоминания через заданное время: минуты, часы, дни. Переживают перезапуск.",
    build=build,
    commands=(("remind", "Поставить напоминание"), ("reminders", "Активные напоминания")),
    background=background,
)
