from abc import ABC, abstractmethod

from aiogram import Bot


class PaymentProvider(ABC):
    """Способ оплаты подписки. Чтобы добавить новый, унаследуйтесь и зарегистрируйте в payments/__init__.py."""

    name: str
    title: str

    @abstractmethod
    async def start(self, bot: Bot, user_id: int, days: int) -> None:
        """Показать пользователю оплату: инвойс, ссылка или реквизиты."""

    async def poll(self) -> list["Settled"]:
        """Для провайдеров без вебхуков: вернуть оплаченные счета. По умолчанию не нужно."""
        return []

    async def aclose(self) -> None:
        return None


class Settled:
    __slots__ = ("provider", "external_id", "user_id", "days", "amount", "currency")

    def __init__(self, provider: str, external_id: str, user_id: int, days: int, amount: str, currency: str):
        self.provider = provider
        self.external_id = external_id
        self.user_id = user_id
        self.days = days
        self.amount = amount
        self.currency = currency
