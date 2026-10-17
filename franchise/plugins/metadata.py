from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..ui import card, title
from .base import PluginContext, PluginSpec


def _origin_lines(message: Message) -> list[tuple[str, str]]:
    origin = message.forward_origin
    if origin is None:
        return []
    kind = origin.type
    if kind == "user":
        src = f"пользователь {origin.sender_user.full_name} (id {origin.sender_user.id})"
    elif kind == "hidden_user":
        src = f"скрытый пользователь «{origin.sender_user_name}»"
    elif kind == "chat":
        src = f"чат {origin.sender_chat.title} (id {origin.sender_chat.id})"
    else:
        src = f"канал {origin.chat.title} (id {origin.chat.id}), пост #{origin.message_id}"
    return [("Переслано от", src), ("Дата исходного", origin.date.strftime("%d.%m.%Y %H:%M"))]


def _file_lines(message: Message) -> list[tuple[str, str]]:
    media = message.document or message.video or message.audio or message.voice or message.animation or message.video_note
    if message.photo:
        photo = message.photo[-1]
        return [("Тип", "фото"), ("Размер", f"{photo.width}×{photo.height}"), ("file_id", photo.file_id)]
    if media is None:
        return []
    lines = [("Тип", message.content_type), ("file_id", media.file_id), ("file_unique_id", media.file_unique_id)]
    if getattr(media, "file_name", None):
        lines.append(("Имя", media.file_name))
    if getattr(media, "mime_type", None):
        lines.append(("MIME", media.mime_type))
    if media.file_size:
        lines.append(("Размер", f"{media.file_size / 1024 / 1024:.2f} МБ"))
    if getattr(media, "duration", None):
        lines.append(("Длительность", f"{media.duration} c"))
    return lines


def build(ctx: PluginContext) -> Router:
    router = Router(name="metadata")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Метаданные", "🔎")
            + "\nПришлите что угодно: сообщение, файл, фото или пересланный пост — покажу все данные.\n\n"
            "/whoami — ваш профиль\n/chat — данные этого чата"
        )

    @router.message(Command("whoami"))
    async def cmd_whoami(message: Message) -> None:
        user = message.from_user
        await message.answer(
            title("Вы", "👤")
            + "\n"
            + card([
                ("ID", str(user.id)),
                ("Имя", user.full_name),
                ("Username", f"@{user.username}" if user.username else "нет"),
                ("Язык", user.language_code or "неизвестен"),
                ("Premium", "да" if user.is_premium else "нет"),
            ])
        )

    @router.message(Command("chat"))
    async def cmd_chat(message: Message) -> None:
        chat = message.chat
        await message.answer(
            title("Чат", "💬")
            + "\n"
            + card([("ID", str(chat.id)), ("Тип", chat.type), ("Название", chat.title or chat.full_name or "—")])
        )

    @router.message()
    async def on_any(message: Message) -> None:
        lines = _origin_lines(message) + _file_lines(message)
        lines.insert(0, ("message_id", str(message.message_id)))
        lines.append(("chat_id", str(message.chat.id)))
        if message.from_user:
            lines.append(("sender_id", str(message.from_user.id)))
        await message.answer(title("Метаданные сообщения", "🔎") + "\n" + card(lines))

    return router


SPEC = PluginSpec(
    name="metadata",
    title="Метаданные",
    icon="🔎",
    description="Показывает ID, данные файлов, источник пересланных постов и профиль пользователя.",
    build=build,
    commands=(("whoami", "Ваш профиль"), ("chat", "Данные чата")),
)
