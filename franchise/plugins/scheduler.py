import asyncio
import re
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import hint, title
from .base import PluginContext, PluginSpec

TZ = ZoneInfo("Europe/Moscow")
QUEUE_KEY = "queue"
CHANNEL_KEY = "channel"
TICK = 20
WHEN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(.+)$", re.DOTALL)


def parse(args: str) -> tuple[int, str] | None:
    match = WHEN_RE.match(args.strip())
    if not match:
        return None
    try:
        when = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        return None
    return int(when.timestamp()), match.group(3).strip()


def build(ctx: PluginContext) -> Router:
    router = Router(name="scheduler")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        channel = ctx.get(CHANNEL_KEY) or "не задан"
        await message.answer(
            title("Отложенные посты", "🗓")
            + f"\nКанал: <b>{channel}</b>\n\n"
            "• /setchannel @username\n"
            "• <code>/schedule 2026-10-20 18:00 текст поста</code> (МСК)\n"
            "• /queue — очередь, /cancel id — отменить\n"
            + hint("Поддерживается HTML-разметка: <b>, <i>, <a href=...>.")
        )

    @router.message(Command("setchannel"))
    async def cmd_setchannel(message: Message, command: CommandObject, bot: Bot) -> None:
        target = (command.args or "").strip()
        try:
            chat = await bot.get_chat(target)
        except TelegramAPIError as exc:
            await message.answer(f"❌ {exc.message}")
            return
        ctx.set(CHANNEL_KEY, str(chat.id))
        await message.answer(f"✅ Канал: <b>{chat.title}</b>")

    @router.message(Command("schedule"))
    async def cmd_schedule(message: Message, command: CommandObject) -> None:
        if not ctx.get(CHANNEL_KEY):
            await message.answer("Сначала выберите канал: /setchannel @username")
            return
        parsed = parse(command.args or "")
        if not parsed:
            await message.answer("Формат: <code>/schedule 2026-10-20 18:00 текст</code>")
            return
        at, text = parsed
        if at <= time.time():
            await message.answer("Это время уже прошло.")
            return
        queue = ctx.get(QUEUE_KEY, [])
        queue.append({"id": uuid.uuid4().hex[:6], "at": at, "text": text})
        ctx.set(QUEUE_KEY, sorted(queue, key=lambda q: q["at"]))
        when = datetime.fromtimestamp(at, TZ).strftime("%d.%m.%Y %H:%M")
        await message.answer(f"🗓 Запланировано на <b>{when}</b> МСК")

    @router.message(Command("queue"))
    async def cmd_queue(message: Message) -> None:
        queue = ctx.get(QUEUE_KEY, [])
        if not queue:
            await message.answer("Очередь пуста.")
            return
        lines = []
        for item in queue:
            when = datetime.fromtimestamp(item["at"], TZ).strftime("%d.%m %H:%M")
            lines.append(f"<code>{item['id']}</code> · {when} · {item['text'][:60]}")
        await message.answer(title("Очередь", "🗓") + "\n" + "\n".join(lines))

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message, command: CommandObject) -> None:
        target = (command.args or "").strip()
        queue = ctx.get(QUEUE_KEY, [])
        remaining = [q for q in queue if q["id"] != target]
        if len(remaining) == len(queue):
            await message.answer("Такого поста нет в очереди.")
            return
        ctx.set(QUEUE_KEY, remaining)
        await message.answer("🗑 Пост снят с очереди.")

    return router


async def background(bot: Bot, ctx: PluginContext) -> None:
    while True:
        await asyncio.sleep(TICK)
        now = time.time()
        channel = ctx.get(CHANNEL_KEY)
        due = [q for q in ctx.get(QUEUE_KEY, []) if q["at"] <= now]
        if not due or not channel:
            continue
        posted: set[str] = set()
        for item in due:
            try:
                await bot.send_message(channel, item["text"], parse_mode="HTML", disable_web_page_preview=False)
                posted.add(item["id"])
            except TelegramAPIError:
                posted.add(item["id"])
        ctx.set(QUEUE_KEY, [q for q in ctx.get(QUEUE_KEY, []) if q["id"] not in posted])


SPEC = PluginSpec(
    name="scheduler",
    title="Отложенные посты",
    icon="🗓",
    description="Планирует публикации в канал на нужную дату и время (по Москве).",
    build=build,
    commands=(("schedule", "Запланировать пост"), ("queue", "Очередь постов")),
    background=background,
    owner_only=True,
)
