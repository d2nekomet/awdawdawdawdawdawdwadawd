import asyncio
import io

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from PIL import Image, ImageOps

from ..ui import hint, title
from .base import PluginContext, PluginSpec

MAX_SIDE = 1600
JPEG_QUALITY = 80


def _process(raw: bytes, grayscale: bool) -> tuple[bytes, tuple[int, int]]:
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if grayscale:
        img = ImageOps.grayscale(img)
    img = img.convert("RGB") if img.mode not in ("L", "RGB") else img
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue(), img.size


def build(ctx: PluginContext) -> Router:
    router = Router(name="images")

    @router.message(F.photo | F.document)
    async def on_image(message: Message, bot: Bot) -> None:
        if message.document and not (message.document.mime_type or "").startswith("image/"):
            return
        file_id = message.photo[-1].file_id if message.photo else message.document.file_id
        grayscale = (message.caption or "").strip().lower() in {"bw", "ч/б", "чб"}
        status = await message.answer("⏳ Обрабатываю…")
        buf = io.BytesIO()
        await bot.download(file_id, destination=buf)
        raw = buf.getvalue()
        try:
            data, (w, h) = await asyncio.to_thread(_process, raw, grayscale)
        except Exception as exc:
            await status.edit_text(f"❌ Не удалось открыть изображение: {str(exc)[:150]}")
            return
        before, after = len(raw) / 1024, len(data) / 1024
        await message.answer_document(
            BufferedInputFile(data, filename="compressed.jpg"),
            caption=(
                f"🖼 {w}×{h} · {before:.0f} → {after:.0f} КБ"
                + (" · ч/б" if grayscale else "")
            ),
        )
        await status.delete()

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Изображения", "🖼")
            + "\nПришлите фото — сожму до JPEG 1600 px.\n"
            "Подпись <code>bw</code> к фото — сделаю чёрно-белым.\n"
            + hint("Исходник: отправляю файлом, чтобы Telegram не пересжимал повторно.")
        )

    return router


SPEC = PluginSpec(
    name="images",
    title="Изображения",
    icon="🖼",
    description="Сжимает фото, поворачивает по EXIF и делает ч/б по подписи bw.",
    build=build,
    commands=(),
)
