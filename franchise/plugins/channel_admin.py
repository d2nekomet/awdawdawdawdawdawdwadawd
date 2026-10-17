from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..ui import keyboard
from .base import PluginContext, PluginSpec

CHANNEL_KEY = "channel"


def build(ctx: PluginContext) -> Router:
    router = Router(name="channel_admin")

    def channel() -> str | None:
        return ctx.get(CHANNEL_KEY)

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        ch = channel() or "не задан"
        await message.answer(
            "📣 <b>Управление каналом</b>\n━━━━━━━━━━━━━━━━\n"
            f"Канал: <b>{ch}</b>\n\n"
            "• /setchannel @username — выбрать канал (бот должен быть админом)\n"
            "• Отправьте любое сообщение — перешлю его в канал после подтверждения\n"
            "• /pin <id> и /unpin <id> — закрепить или открепить пост\n"
            "• /del <id> — удалить пост"
        )

    @router.message(Command("setchannel"))
    async def cmd_setchannel(message: Message, command: CommandObject, bot: Bot) -> None:
        target = (command.args or "").strip()
        if not target:
            await message.answer("Укажите канал: <code>/setchannel @my_channel</code>")
            return
        try:
            chat = await bot.get_chat(target)
            me = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        except TelegramAPIError as exc:
            await message.answer(f"❌ Не получилось открыть канал: {exc.message}")
            return
        if me.status not in ("administrator", "creator"):
            await message.answer("❌ Бот не админ этого канала. Добавьте его с правом публикации.")
            return
        ctx.set(CHANNEL_KEY, str(chat.id))
        await message.answer(f"✅ Канал выбран: <b>{chat.title}</b>")

    async def _need_channel(message: Message) -> str | None:
        ch = channel()
        if not ch:
            await message.answer("Сначала выберите канал: /setchannel @username")
        return ch

    @router.message(Command("pin", "unpin", "del"))
    async def cmd_moderate(message: Message, command: CommandObject, bot: Bot) -> None:
        ch = await _need_channel(message)
        if not ch:
            return
        if not command.args or not command.args.strip().isdigit():
            await message.answer("Укажите id поста: <code>/pin 123</code>")
            return
        msg_id = int(command.args.strip())
        try:
            if command.command == "pin":
                await bot.pin_chat_message(ch, msg_id, disable_notification=True)
                text = "📌 Закреплено"
            elif command.command == "unpin":
                await bot.unpin_chat_message(ch, msg_id)
                text = "📍 Откреплено"
            else:
                await bot.delete_message(ch, msg_id)
                text = "🗑 Удалено"
        except TelegramAPIError as exc:
            text = f"❌ {exc.message}"
        await message.answer(text)

    @router.message(F.text & ~F.text.startswith("/"))
    @router.message(F.photo | F.video | F.document | F.animation | F.audio | F.voice)
    async def on_draft(message: Message) -> None:
        if not channel():
            await message.answer("Сначала выберите канал: /setchannel @username")
            return
        await message.reply(
            "Опубликовать это сообщение в канал?",
            reply_markup=keyboard([[("✅ Опубликовать", f"pub:{message.message_id}"), ("❌ Отмена", "pub:cancel")]]),
        )

    @router.callback_query(F.data.startswith("pub:"))
    async def on_publish(query: CallbackQuery, bot: Bot) -> None:
        action = query.data.split(":", 1)[1]
        if action == "cancel":
            await query.message.edit_text("Публикация отменена.")
            await query.answer()
            return
        ch = channel()
        if not ch or query.message.chat.id != query.from_user.id:
            await query.answer("Канал не выбран", show_alert=True)
            return
        try:
            sent = await bot.copy_message(chat_id=ch, from_chat_id=query.from_user.id, message_id=int(action))
        except TelegramAPIError as exc:
            await query.answer(f"Ошибка: {exc.message}", show_alert=True)
            return
        await query.message.edit_text(f"✅ Опубликовано. ID поста: <code>{sent.message_id}</code>")
        await query.answer()

    return router


SPEC = PluginSpec(
    name="channel_admin",
    title="Управление каналом",
    icon="📣",
    description="Публикация постов, закрепление, удаление и управление каналом через бота.",
    build=build,
    commands=(
        ("setchannel", "Выбрать канал"),
        ("pin", "Закрепить пост"),
        ("unpin", "Открепить пост"),
        ("del", "Удалить пост"),
    ),
    owner_only=True,
)
