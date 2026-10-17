import asyncio
import logging
import time
from datetime import datetime, timezone

from aiogram import Bot

from .config import Settings
from .db import Database
from .payments import PaymentProvider, Settled

log = logging.getLogger(__name__)

POLL_INTERVAL = 30


def format_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


class Billing:
    def __init__(self, db: Database, settings: Settings, providers: dict[str, PaymentProvider]):
        self.db = db
        self.settings = settings
        self.providers = providers

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.settings.admin_ids

    def has_access(self, user_id: int) -> bool:
        return self.is_admin(user_id) or self.db.subscription_expires(user_id) > time.time()

    def expires_text(self, user_id: int) -> str | None:
        expires = self.db.subscription_expires(user_id)
        return format_ts(expires) if expires > time.time() else None

    def grant(self, settled: Settled) -> int:
        """Зачисляет дни один раз на (провайдер, external_id). Возвращает timestamp окончания подписки или 0."""
        if self.db.get_payment(settled.provider, settled.external_id) is None:
            self.db.insert_paid_payment(
                settled.provider, settled.external_id, settled.user_id, settled.days,
                settled.amount, settled.currency,
            )
        elif not self.db.mark_payment_paid(settled.provider, settled.external_id):
            return 0
        return self.db.extend_subscription(settled.user_id, settled.days)

    async def run_pollers(self, bot: Bot) -> None:
        pollers = [p for p in self.providers.values() if type(p).poll is not PaymentProvider.poll]
        if not pollers:
            return
        while True:
            for provider in pollers:
                try:
                    settled_list = await provider.poll()
                except Exception:
                    log.exception("poll failed for %s", provider.name)
                    continue
                for settled in settled_list:
                    expires = self.grant(settled)
                    if expires:
                        await _notify_paid(bot, settled.user_id, expires)
            await asyncio.sleep(POLL_INTERVAL)


async def _notify_paid(bot: Bot, user_id: int, expires: int) -> None:
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>Оплата получена</b>\n\nПодписка активна до <b>{format_ts(expires)}</b>.\n"
            "Все боты франшизы теперь доступны бесплатно.",
        )
    except Exception:
        log.exception("failed to notify %s", user_id)
