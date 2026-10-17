import asyncio
import io

import qrcode
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from .base import PluginContext, PluginSpec

MAX_LEN = 2000


def _render(text: str) -> bytes:
    qr = qrcode.QRCode(box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def build(ctx: PluginContext) -> Router:
    router = Router(name="qr")

    async def send(message: Message, text: str) -> None:
        if not text.strip():
            await message.answer("Пришлите текст или ссылку — сделаю QR-код.")
            return
        if len(text) > MAX_LEN:
            await message.answer(f"❌ Слишком длинный текст (максимум {MAX_LEN} символов).")
            return
        png = await asyncio.to_thread(_render, text)
        await message.answer_photo(
            BufferedInputFile(png, filename="qr.png"),
            caption=f"🔳 <code>{text[:200]}</code>",
        )

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            "🔳 <b>QR-коды</b>\n━━━━━━━━━━━━━━━━\n"
            "Пришлите текст или ссылку — верну QR-код.\n"
            "Или: <code>/qr https://example.com</code>"
        )

    @router.message(Command("qr"))
    async def cmd_qr(message: Message, command: CommandObject) -> None:
        await send(message, command.args or "")

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        await send(message, message.text or "")

    return router


SPEC = PluginSpec(
    name="qr",
    title="QR-генератор",
    icon="🔳",
    description="Превращает текст и ссылки в QR-коды.",
    build=build,
    commands=(("qr", "Сделать QR-код"),),
)
