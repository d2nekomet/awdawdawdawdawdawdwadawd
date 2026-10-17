import re

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import hint, title
from .base import PluginContext, PluginSpec

LANG_RE = re.compile(r"^[a-z]{2}$")
MAX_LEN = 4000


def build(ctx: PluginContext) -> Router:
    router = Router(name="translator")
    settings = ctx.services.settings
    http = ctx.services.http

    async def translate(text: str, target: str) -> tuple[str, str]:
        body = {"q": text, "source": "auto", "target": target, "format": "text"}
        if settings.translate_api_key:
            body["api_key"] = settings.translate_api_key
        resp = await http.post(settings.translate_url, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        detected = (data.get("detectedLanguage") or {}).get("language", "?")
        return data["translatedText"], detected

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Перевод", "🌐")
            + "\n• <code>/tr en Привет, мир</code> — перевести на английский\n"
            "• Просто пришлите текст — переведу на английский\n"
            + hint("Код языка: en, ru, de, fr, es, zh, ja…")
        )

    @router.message(Command("tr"))
    async def cmd_tr(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split(maxsplit=1)
        if len(parts) != 2 or not LANG_RE.match(parts[0].lower()):
            await message.answer("Формат: <code>/tr en текст</code>")
            return
        await _reply(message, parts[1], parts[0].lower())

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        await _reply(message, message.text or "", "en")

    async def _reply(message: Message, text: str, target: str) -> None:
        if len(text) > MAX_LEN:
            await message.answer(f"❌ Текст длиннее {MAX_LEN} символов.")
            return
        try:
            result, detected = await translate(text, target)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            await message.answer(f"❌ Сервис перевода недоступен: {str(exc)[:150]}")
            return
        await message.answer(f"🌐 <b>{detected} → {target}</b>\n━━━━━━━━━━━━━━━━\n{result}")

    return router


SPEC = PluginSpec(
    name="translator",
    title="Переводчик",
    icon="🌐",
    description="Переводит текст между языками. Язык определяется автоматически.",
    build=build,
    commands=(("tr", "Перевести: /tr en текст"),),
)
