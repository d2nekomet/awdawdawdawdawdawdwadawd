import base64
import binascii
import hashlib
import re
import unicodedata

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import card, hint, title
from .base import PluginContext, PluginSpec

MAX_LEN = 3500


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")


def build(ctx: PluginContext) -> Router:
    router = Router(name="text_tools")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Текстовые инструменты", "🔤")
            + "\n"
            "/upper, /lower, /title — регистр\n"
            "/count — слова, символы, строки\n"
            "/b64 и /unb64 — base64\n"
            "/sha256 и /md5 — хеши\n"
            "/slug — URL-slug\n"
            + hint("Команда + текст в той же строке или ответом на сообщение.")
        )

    async def _text(message: Message, command: CommandObject) -> str | None:
        text = command.args or (message.reply_to_message.text if message.reply_to_message else None)
        if not text:
            await message.answer("Пришлите текст после команды или ответьте на сообщение.")
            return None
        if len(text) > MAX_LEN:
            await message.answer(f"❌ Максимум {MAX_LEN} символов.")
            return None
        return text

    @router.message(Command("upper", "lower", "title"))
    async def cmd_case(message: Message, command: CommandObject) -> None:
        text = await _text(message, command)
        if text is None:
            return
        fn = {"upper": str.upper, "lower": str.lower, "title": str.title}[command.command]
        await message.answer(f"<code>{fn(text)}</code>")

    @router.message(Command("count"))
    async def cmd_count(message: Message, command: CommandObject) -> None:
        text = await _text(message, command)
        if text is None:
            return
        await message.answer(
            title("Статистика", "🔢")
            + "\n"
            + card([
                ("Слова", str(len(text.split()))),
                ("Символы", str(len(text))),
                ("Без пробелов", str(len(re.sub(r"\s", "", text)))),
                ("Строки", str(len(text.splitlines()) or 1)),
            ])
        )

    @router.message(Command("b64"))
    async def cmd_b64(message: Message, command: CommandObject) -> None:
        text = await _text(message, command)
        if text is not None:
            await message.answer(f"<code>{base64.b64encode(text.encode()).decode()}</code>")

    @router.message(Command("unb64"))
    async def cmd_unb64(message: Message, command: CommandObject) -> None:
        text = await _text(message, command)
        if text is None:
            return
        try:
            decoded = base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            await message.answer("❌ Это не base64 или не UTF-8 текст.")
            return
        await message.answer(f"<code>{decoded}</code>")

    @router.message(Command("sha256", "md5"))
    async def cmd_hash(message: Message, command: CommandObject) -> None:
        text = await _text(message, command)
        if text is None:
            return
        digest = hashlib.new(command.command, text.encode()).hexdigest()
        await message.answer(f"<b>{command.command.upper()}</b>\n<code>{digest}</code>")

    @router.message(Command("slug"))
    async def cmd_slug(message: Message, command: CommandObject) -> None:
        text = await _text(message, command)
        if text is not None:
            await message.answer(f"<code>{_slug(text) or '—'}</code>")

    return router


SPEC = PluginSpec(
    name="text_tools",
    title="Текст и хеши",
    icon="🔤",
    description="Регистр, подсчёт слов, base64, SHA-256, MD5 и URL-slug.",
    build=build,
    commands=(("count", "Статистика текста"), ("b64", "Кодировать base64"), ("sha256", "SHA-256")),
)
