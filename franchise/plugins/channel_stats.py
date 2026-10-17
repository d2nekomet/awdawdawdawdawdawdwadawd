import asyncio
import logging
import time
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import card, title
from .base import PluginContext, PluginSpec

log = logging.getLogger(__name__)

CHANNEL_KEY = "channel"
HISTORY_KEY = "history"
SNAPSHOT_EVERY = 6 * 3600
MAX_HISTORY = 1000


async def _snapshot(bot: Bot, ctx: PluginContext) -> dict | None:
    channel = ctx.get(CHANNEL_KEY)
    if not channel:
        return None
    count = await bot.get_chat_member_count(channel)
    admins = await bot.get_chat_administrators(channel)
    snap = {"ts": int(time.time()), "members": count, "admins": len(admins)}
    history = ctx.get(HISTORY_KEY, [])
    history.append(snap)
    ctx.set(HISTORY_KEY, history[-MAX_HISTORY:])
    return snap


def _delta(history: list[dict], days: int) -> tuple[int, int] | None:
    if len(history) < 2:
        return None
    cutoff = time.time() - days * 86400
    window = [h for h in history if h["ts"] >= cutoff] or history[-2:]
    first, last = window[0], window[-1]
    return last["members"] - first["members"], last["members"]


def build(ctx: PluginContext) -> Router:
    router = Router(name="channel_stats")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Аналитика канала", "📈")
            + "\n• /setchannel @username — выбрать канал\n"
            "• /stats — подписчики и админы прямо сейчас\n"
            "• /growth — динамика за 7 и 30 дней"
        )

    @router.message(Command("setchannel"))
    async def cmd_setchannel(message: Message, command: CommandObject, bot: Bot) -> None:
        target = (command.args or "").strip()
        if not target:
            await message.answer("Укажите канал: <code>/setchannel @my_channel</code>")
            return
        try:
            chat = await bot.get_chat(target)
        except TelegramAPIError as exc:
            await message.answer(f"❌ {exc.message}")
            return
        ctx.set(CHANNEL_KEY, str(chat.id))
        await message.answer(f"✅ Канал: <b>{chat.title}</b>")

    @router.message(Command("stats"))
    async def cmd_stats(message: Message, bot: Bot) -> None:
        if not ctx.get(CHANNEL_KEY):
            await message.answer("Сначала выберите канал: /setchannel @username")
            return
        try:
            snap = await _snapshot(bot, ctx)
        except TelegramAPIError as exc:
            await message.answer(f"❌ {exc.message}")
            return
        await message.answer(
            title("Канал сейчас", "📊")
            + "\n"
            + card([("Подписчики", f"{snap['members']:,}".replace(",", " ")), ("Администраторы", str(snap["admins"]))])
        )

    @router.message(Command("growth"))
    async def cmd_growth(message: Message) -> None:
        history = ctx.get(HISTORY_KEY, [])
        week, month = _delta(history, 7), _delta(history, 30)
        if not week:
            await message.answer("Пока мало данных. Снимки делаются при /stats и каждые 6 часов.")
            return
        lines = [("За 7 дней", f"{week[0]:+d}")]
        if month:
            lines.append(("За 30 дней", f"{month[0]:+d}"))
        lines.append(("Всего сейчас", str(week[1])))
        await message.answer(title("Динамика", "📈") + "\n" + card(lines))

    return router


async def background(bot: Bot, ctx: PluginContext) -> None:
    while True:
        await asyncio.sleep(SNAPSHOT_EVERY)
        try:
            await _snapshot(bot, ctx)
        except Exception:
            log.exception("channel snapshot failed for owner %s", ctx.owner_id)


SPEC = PluginSpec(
    name="channel_stats",
    title="Аналитика канала",
    icon="📈",
    description="Подписчики, админы и динамика роста канала. Снимки ведутся автоматически.",
    build=build,
    commands=(("stats", "Статистика канала"), ("growth", "Динамика роста")),
    background=background,
    owner_only=True,
)
