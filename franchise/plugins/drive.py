import io

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from .base import PluginContext, PluginSpec

MAX_BOT_DOWNLOAD = 20 * 1024 * 1024
RECENT_KEY = "recent"


def _file_of(message: Message):
    if message.document:
        return message.document.file_id, message.document.file_name or "file", message.document.file_size, message.document.mime_type
    if message.video:
        return message.video.file_id, message.video.file_name or f"{message.video.file_unique_id}.mp4", message.video.file_size, message.video.mime_type
    if message.audio:
        return message.audio.file_id, message.audio.file_name or f"{message.audio.file_unique_id}.mp3", message.audio.file_size, message.audio.mime_type
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, f"{photo.file_unique_id}.jpg", photo.file_size, "image/jpeg"
    return None


def build(ctx: PluginContext) -> Router:
    router = Router(name="drive")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        state = "подключён ✅" if ctx.services.drive.configured else "не настроен ⚠️"
        await message.answer(
            "☁️ <b>Сохранение в Drive</b>\n━━━━━━━━━━━━━━━━\n"
            "Отправьте файл, фото или видео — я сохраню его в облаке и пришлю ссылку.\n\n"
            f"Статус Drive: {state}\n/list — последние 10 загрузок"
        )

    @router.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        recent = ctx.get(RECENT_KEY, [])
        if not recent:
            await message.answer("Пока пусто. Отправьте файл.")
            return
        lines = [f"{i}. <a href=\"{item['url']}\">{item['name']}</a>" for i, item in enumerate(recent[-10:][::-1], 1)]
        await message.answer("📂 <b>Последние загрузки</b>\n\n" + "\n".join(lines), disable_web_page_preview=True)

    @router.message(F.document | F.video | F.audio | F.photo)
    async def on_file(message: Message, bot: Bot) -> None:
        found = _file_of(message)
        if not found:
            return
        file_id, name, size, mime = found
        if size and size > MAX_BOT_DOWNLOAD:
            await message.answer("❌ Файл больше 20 МБ — Bot API не отдаёт такие файлы боту.")
            return
        if not ctx.services.drive.configured:
            await message.answer("⚠️ Drive не настроен: задайте DRIVE_UPLOAD_URL и DRIVE_API_TOKEN.")
            return
        status = await message.answer("⏳ Загружаю в Drive…")
        buf = io.BytesIO()
        try:
            await bot.download(file_id, destination=buf)
            url = await ctx.services.drive.upload(name, buf.getvalue(), mime or "application/octet-stream")
        except Exception as exc:
            await status.edit_text(f"❌ Ошибка загрузки: {str(exc)[:200]}")
            return
        recent = ctx.get(RECENT_KEY, [])
        recent.append({"name": name, "url": url})
        ctx.set(RECENT_KEY, recent[-50:])
        await status.edit_text(f"✅ <b>{name}</b> сохранён\n<a href=\"{url}\">{url}</a>", disable_web_page_preview=True)

    return router


SPEC = PluginSpec(
    name="drive",
    title="Сохранение в Drive",
    icon="☁️",
    description="Принимает файлы, фото и видео и сохраняет их в drive.unlim-projects.lol.",
    build=build,
    commands=(("list", "Последние загрузки"),),
    owner_only=True,
)
