from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import hint, title
from .base import PluginContext, PluginSpec


def build(ctx: PluginContext) -> Router:
    router = Router(name="polls")

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Опросы", "📊")
            + "\nФормат: <code>/poll Что на обед? | Суши | Пицца | Бургер</code>\n"
            + hint("От 2 до 10 вариантов. Опрос анонимный и с выбором нескольких ответов.")
        )

    @router.message(Command("poll"))
    async def cmd_poll(message: Message, command: CommandObject) -> None:
        parts = [p.strip() for p in (command.args or "").split("|") if p.strip()]
        if len(parts) < 3:
            await message.answer("Нужны вопрос и минимум 2 варианта, через «|».")
            return
        question, options = parts[0][:300], [o[:100] for o in parts[1:11]]
        await message.answer_poll(
            question=question,
            options=options,
            is_anonymous=True,
            allows_multiple_answers=True,
        )

    return router


SPEC = PluginSpec(
    name="polls",
    title="Опросы",
    icon="📊",
    description="Создаёт опросы из одной строки: вопрос и до 10 вариантов.",
    build=build,
    commands=(("poll", "Создать опрос"),),
)
