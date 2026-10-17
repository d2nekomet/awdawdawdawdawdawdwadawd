import secrets

from aiogram import Bot
from aiogram.types import LabeledPrice

from .base import PaymentProvider

PAYLOAD_PREFIX = "stars"
CURRENCY = "XTR"


def make_payload(user_id: int, days: int) -> str:
    return f"{PAYLOAD_PREFIX}:{user_id}:{days}:{secrets.token_hex(4)}"


def parse_payload(payload: str) -> tuple[int, int] | None:
    parts = payload.split(":")
    if len(parts) != 4 or parts[0] != PAYLOAD_PREFIX:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


class StarsProvider(PaymentProvider):
    name = "stars"
    title = "⭐ Telegram Stars"

    def __init__(self, price: int):
        self.price = price

    async def start(self, bot: Bot, user_id: int, days: int) -> None:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"Подписка на {days} дн.",
            description="Доступ ко всем ботам франшизы без дополнительной оплаты.",
            payload=make_payload(user_id, days),
            currency=CURRENCY,
            prices=[LabeledPrice(label=f"Подписка {days} дн.", amount=self.price)],
        )
