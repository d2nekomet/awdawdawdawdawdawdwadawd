import asyncio
import re
import shutil
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message
from yt_dlp import YoutubeDL

from .base import PluginContext, PluginSpec

URL_RE = re.compile(r"https?://(?:[\w-]+\.)?(?:tiktok\.com|vm\.tiktok\.com)/\S+", re.IGNORECASE)
MAX_BYTES = 50 * 1024 * 1024


def _download(url: str, out_dir: Path) -> tuple[Path, str]:
    opts = {
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "format": "mp4/best[ext=mp4]/best",
        "max_filesize": MAX_BYTES,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info)), info.get("title") or "TikTok"


def build(ctx: PluginContext) -> Router:
    router = Router(name="tiktok")

    async def handle(message: Message, url: str) -> None:
        status = await message.answer("⏳ Скачиваю видео…")
        tmp = Path(tempfile.mkdtemp(prefix="tt_"))
        try:
            path, title = await asyncio.to_thread(_download, url, tmp)
            if path.stat().st_size > MAX_BYTES:
                await status.edit_text("❌ Видео больше 50 МБ — лимит Telegram Bot API.")
                return
            await message.answer_video(FSInputFile(path), caption=f"🎬 {title[:200]}")
            await status.delete()
        except Exception as exc:
            await status.edit_text(f"❌ Не удалось скачать: {str(exc)[:200]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @router.message(Command("tt", "tiktok"))
    async def cmd_tt(message: Message, command: CommandObject) -> None:
        match = URL_RE.search(command.args or "")
        if not match:
            await message.answer("Пришлите ссылку на TikTok: <code>/tt https://vm.tiktok.com/...</code>")
            return
        await handle(message, match.group(0))

    @router.message(F.text.regexp(URL_RE))
    async def on_link(message: Message) -> None:
        match = URL_RE.search(message.text or "")
        if match:
            await handle(message, match.group(0))

    return router


SPEC = PluginSpec(
    name="tiktok",
    title="TikTok загрузчик",
    icon="🎬",
    description="Скачивает видео из TikTok без водяного знака. Пришлите ссылку — получите файл.",
    build=build,
    commands=(("tt", "Скачать видео по ссылке"),),
)
