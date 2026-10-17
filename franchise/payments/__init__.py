import httpx

from ..config import Settings
from ..db import Database
from .base import PaymentProvider, Settled
from .cryptobot import CryptoBotProvider
from .stars import StarsProvider

__all__ = ["PaymentProvider", "Settled", "build_providers"]


def build_providers(settings: Settings, db: Database) -> dict[str, PaymentProvider]:
    """Собирает только включённые в ENABLED_PAYMENTS провайдеры. Новый способ — одна строка тут."""
    providers: dict[str, PaymentProvider] = {}
    for name in settings.enabled_payments:
        if name == "stars":
            providers[name] = StarsProvider(price=settings.stars_price)
        elif name == "cryptobot":
            if not settings.cryptobot_token:
                raise RuntimeError("ENABLED_PAYMENTS содержит cryptobot, но CRYPTOBOT_TOKEN пуст")
            providers[name] = CryptoBotProvider(
                token=settings.cryptobot_token,
                db=db,
                http=httpx.AsyncClient(timeout=15),
                asset=settings.cryptobot_asset,
                amount=settings.cryptobot_amount,
                testnet=settings.cryptobot_testnet,
            )
        else:
            raise RuntimeError(f"Неизвестный способ оплаты: {name}")
    return providers
