from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..ui import hint, keyboard, title
from .base import PluginContext, PluginSpec

MAX_ITEMS = 100


def build(ctx: PluginContext) -> Router:
    router = Router(name="notes")

    def key(user_id: int) -> str:
        return f"list:{user_id}"

    def items(user_id: int) -> list[dict]:
        return ctx.get(key(user_id), [])

    def render(user_id: int) -> tuple[str, list[list[tuple[str, str]]]]:
        data = items(user_id)
        if not data:
            return title("Список дел", "📝") + "\n" + hint("Пусто. Добавьте: /add купить молоко"), []
        done = sum(1 for i in data if i["done"])
        lines = []
        rows = []
        for idx, item in enumerate(data):
            mark = "✅" if item["done"] else "⬜"
            lines.append(f"{mark} {item['text']}")
            rows.append([(f"{mark} {idx + 1}", f"nt:t:{idx}"), ("🗑", f"nt:d:{idx}")])
        header = title("Список дел", "📝") + f"\n{done}/{len(data)} выполнено\n\n"
        rows.append([("🧹 Убрать выполненные", "nt:clear")])
        return header + "\n".join(lines), rows

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Заметки и дела", "📝")
            + "\n• /add текст — добавить пункт\n• /list — список с кнопками\n"
            "• /clear — очистить всё"
        )

    @router.message(Command("add"))
    async def cmd_add(message: Message, command: CommandObject) -> None:
        text = (command.args or "").strip()
        if not text:
            await message.answer("Напишите текст: <code>/add купить молоко</code>")
            return
        data = items(message.from_user.id)
        if len(data) >= MAX_ITEMS:
            await message.answer(f"Лимит {MAX_ITEMS} пунктов. Очистите список: /clear")
            return
        data.append({"text": text[:300], "done": False})
        ctx.set(key(message.from_user.id), data)
        await message.answer(f"➕ Добавлено: {text[:300]}\n/list — посмотреть")

    @router.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        text, rows = render(message.from_user.id)
        await message.answer(text, reply_markup=keyboard(rows) if rows else None)

    @router.message(Command("clear"))
    async def cmd_clear(message: Message) -> None:
        ctx.set(key(message.from_user.id), [])
        await message.answer("🧹 Список очищен.")

    @router.callback_query(F.data.startswith("nt:"))
    async def on_action(query: CallbackQuery) -> None:
        user_id = query.from_user.id
        _, action, *rest = query.data.split(":")
        data = items(user_id)
        if action == "clear":
            data = [i for i in data if not i["done"]]
        elif rest and rest[0].isdigit() and int(rest[0]) < len(data):
            idx = int(rest[0])
            if action == "t":
                data[idx]["done"] = not data[idx]["done"]
            elif action == "d":
                data.pop(idx)
        ctx.set(key(user_id), data)
        text, rows = render(user_id)
        await query.message.edit_text(text, reply_markup=keyboard(rows) if rows else None)
        await query.answer()

    return router


SPEC = PluginSpec(
    name="notes",
    title="Заметки и дела",
    icon="📝",
    description="Личный список дел с кнопками: добавляйте пункты и отмечайте выполненные.",
    build=build,
    commands=(("add", "Добавить пункт"), ("list", "Список дел"), ("clear", "Очистить")),
)
