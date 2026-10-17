import logging

import httpx
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import Database
from .base import PaymentProvider, Settled

log = logging.getLogger(__name__)

MAINNET = "https://pay.crypt.bot/api"
TESTNET = "https://testnet-pay.crypt.bot/api"


class CryptoBotProvider(PaymentProvider):
    """Crypto Pay API (@CryptoBot). Счета проверяются опросом, поэтому вебхук и белый IP не нужны."""

    name = "cryptobot"
    title = "🪙 Crypto Bot"

    def __init__(
        self,
        token: str,
        db: Database,
        http: httpx.AsyncClient,
        asset: str,
        amount: str,
        testnet: bool = False,
    ):
        self.db = db
        self.asset = asset
        self.amount = amount
        self._http = http
        self._base = TESTNET if testnet else MAINNET
        self._headers = {"Crypto-Pay-API-Token": token}

    async def _call(self, method: str, *, get: bool = False, **params) -> dict:
        url = f"{self._base}/{method}"
        if get:
            resp = await self._http.get(url, params=params, headers=self._headers)
        else:
            resp = await self._http.post(url, json=params, headers=self._headers)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Crypto Pay {method}: {data.get('error')}")
        return data["result"]

    async def start(self, bot: Bot, user_id: int, days: int) -> None:
        invoice = await self._call(
            "createInvoice",
            currency_type="crypto",
            asset=self.asset,
            amount=self.amount,
            description=f"Подписка на {days} дн.",
            payload=f"{user_id}:{days}",
            expires_in=3600,
        )
        external_id = str(invoice["invoice_id"])
        self.db.create_pending_payment(self.name, external_id, user_id, days, self.amount, self.asset)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"Оплатить {self.amount} {self.asset}", url=invoice["bot_invoice_url"])
        kb.adjust(1)
        await bot.send_message(
            user_id,
            f"🪙 <b>Счёт создан</b>\n\nСумма: <b>{self.amount} {self.asset}</b>\n"
            f"Срок оплаты: 1 час.\nПодписка активируется автоматически после оплаты.",
            reply_markup=kb.as_markup(),
        )

    async def poll(self) -> list[Settled]:
        pending = self.db.pending_payments(self.name)
        if not pending:
            return []
        settled: list[Settled] = []
        for chunk_start in range(0, len(pending), 100):
            chunk = pending[chunk_start : chunk_start + 100]
            ids = ",".join(p.external_id for p in chunk)
            try:
                result = await self._call("getInvoices", get=True, invoice_ids=ids)
            except (httpx.HTTPError, RuntimeError) as exc:
                log.warning("cryptobot poll failed: %s", exc)
                continue
            by_id = {p.external_id: p for p in chunk}
            for item in result.get("items", []):
                external_id = str(item["invoice_id"])
                payment = by_id.get(external_id)
                if payment is None:
                    continue
                if item["status"] == "paid":
                    settled.append(
                        Settled(self.name, external_id, payment.user_id, payment.days, payment.amount, payment.currency)
                    )
                elif item["status"] == "expired":
                    self.db.set_payment_status(self.name, external_id, "expired")
        return settled

    async def aclose(self) -> None:
        await self._http.aclose()
