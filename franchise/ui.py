"""Единый визуальный стиль: заголовки, разделители, клавиатуры."""

from html import escape

from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup

DIV = "━━━━━━━━━━━━━━━━"


def title(text: str, icon: str = "") -> str:
    head = f"{icon} " if icon else ""
    return f"{head}<b>{escape(text)}</b>\n{DIV}"


def card(lines: list[tuple[str, str]]) -> str:
    return "\n".join(f"<b>{escape(k)}:</b> {escape(v)}" for k, v in lines)


def hint(text: str) -> str:
    return f"<i>{escape(text)}</i>"


def keyboard(rows: list[list[tuple[str, str]]] | None = None, urls: list[list[tuple[str, str]]] | None = None) -> InlineKeyboardMarkup:
    """rows: [[(текст, callback_data), ...], ...]; urls: [[(текст, url), ...]] — добавляются сверху."""
    kb = InlineKeyboardBuilder()
    for row in urls or []:
        for text, url in row:
            kb.button(text=text, url=url)
        kb.adjust(len(row))
    for row in rows or []:
        for text, data in row:
            kb.button(text=text, callback_data=data)
        kb.adjust(len(row))
    return kb.as_markup()
