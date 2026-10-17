import asyncio
import logging
import re
import uuid

import httpx
from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import card, hint, title
from .base import PluginContext, PluginSpec

log = logging.getLogger(__name__)

API = "https://api.coingecko.com/api/v3/simple/price"
COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "ton": "the-open-network",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "doge": "dogecoin",
    "ada": "cardano",
    "trx": "tron",
    "usdt": "tether",
    "ltc": "litecoin",
    "avax": "avalanche-2",
    "link": "chainlink",
    "dot": "polkadot",
}
ALERTS_KEY = "alerts"
MAX_ALERTS = 10
MAX_COINS_PER_PRICE = 10
TICK = 60
ALERT_RE = re.compile(r"^([\w-]+)\s+(above|below|выше|ниже)\s+([\d][\d\s.,]*)$", re.IGNORECASE)
OPS = {"above": "above", "выше": "above", "below": "below", "ниже": "below"}
OP_TEXT = {"above": "выше", "below": "ниже"}


def coin_id(symbol: str) -> str:
    key = symbol.lower()
    return COINS.get(key, key)


def parse_alert(args: str) -> tuple[str, str, float] | None:
    match = ALERT_RE.match(args.strip())
    if not match:
        return None
    try:
        target = float(match.group(3).replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    if target <= 0:
        return None
    return coin_id(match.group(1)), OPS[match.group(2).lower()], target


def is_triggered(op: str, target: float, price: float) -> bool:
    return price >= target if op == "above" else price <= target


def fmt_price(value: float) -> str:
    if value >= 1:
        return f"{value:,.2f}".replace(",", " ")
    return f"{value:.6f}".rstrip("0")


async def fetch_prices(http: httpx.AsyncClient, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    resp = await http.get(
        API,
        params={"ids": ",".join(sorted(set(ids))), "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def build(ctx: PluginContext) -> Router:
    router = Router(name="crypto_alerts")
    http = ctx.services.http

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Крипто-алерты", "📉")
            + "\n• <code>/price btc eth sol</code> — цены и изменение за 24 ч\n"
            "• <code>/alert btc above 70000</code> — сообщить, когда цена дойдёт до уровня\n"
            "• <code>/alert eth below 3000</code>\n"
            "• /alerts — ваши алерты, /delalert id — удалить\n"
            + hint("Данные: CoinGecko, обновление раз в минуту. Не финансовая рекомендация.")
        )

    @router.message(Command("price"))
    async def cmd_price(message: Message, command: CommandObject) -> None:
        symbols = (command.args or "").split()[:MAX_COINS_PER_PRICE]
        if not symbols:
            await message.answer("Укажите монеты: <code>/price btc eth</code>")
            return
        ids = [coin_id(s) for s in symbols]
        try:
            data = await fetch_prices(http, ids)
        except httpx.HTTPError:
            await message.answer("❌ Сервис цен недоступен, попробуйте через минуту.")
            return
        lines = []
        for symbol, cid in zip(symbols, ids):
            entry = data.get(cid)
            if not entry:
                lines.append(f"<b>{symbol.upper()}</b> — не найдено")
                continue
            change = entry.get("usd_24h_change") or 0.0
            arrow = "🟢" if change >= 0 else "🔴"
            lines.append(f"{arrow} <b>{symbol.upper()}</b> {fmt_price(entry['usd'])} $ ({change:+.2f}%)")
        await message.answer(title("Курсы", "📉") + "\n" + "\n".join(lines))

    @router.message(Command("alert"))
    async def cmd_alert(message: Message, command: CommandObject) -> None:
        parsed = parse_alert(command.args or "")
        if not parsed:
            await message.answer("Формат: <code>/alert btc above 70000</code> или <code>below</code>, <code>выше</code>, <code>ниже</code>.")
            return
        coin, op, target = parsed
        alerts = ctx.get(ALERTS_KEY, [])
        mine = [a for a in alerts if a["chat_id"] == message.chat.id]
        if len(mine) >= MAX_ALERTS:
            await message.answer(f"Лимит {MAX_ALERTS} алертов. Удалите ненужные: /alerts")
            return
        try:
            data = await fetch_prices(http, [coin])
        except httpx.HTTPError:
            await message.answer("❌ Сервис цен недоступен, попробуйте через минуту.")
            return
        entry = data.get(coin)
        if not entry:
            await message.answer("Не знаю такую монету. Используйте тикер, например btc или eth.")
            return
        alert = {
            "id": uuid.uuid4().hex[:6],
            "chat_id": message.chat.id,
            "coin": coin,
            "symbol": (command.args or "").split()[0].upper(),
            "op": op,
            "target": target,
        }
        alerts.append(alert)
        ctx.set(ALERTS_KEY, alerts)
        await message.answer(
            f"🔔 Алерт <code>{alert['id']}</code>: {alert['symbol']} {OP_TEXT[op]} {fmt_price(target)} $\n"
            f"Сейчас {fmt_price(entry['usd'])} $"
        )

    @router.message(Command("alerts"))
    async def cmd_alerts(message: Message) -> None:
        mine = [a for a in ctx.get(ALERTS_KEY, []) if a["chat_id"] == message.chat.id]
        if not mine:
            await message.answer("Активных алертов нет. Создайте: /alert btc above 70000")
            return
        lines = [f"<code>{a['id']}</code> · {a['symbol']} {OP_TEXT[a['op']]} {fmt_price(a['target'])} $" for a in mine]
        await message.answer(title("Ваши алерты", "🔔") + "\n" + "\n".join(lines))

    @router.message(Command("delalert"))
    async def cmd_delalert(message: Message, command: CommandObject) -> None:
        target_id = (command.args or "").strip()
        alerts = ctx.get(ALERTS_KEY, [])
        remaining = [a for a in alerts if not (a["id"] == target_id and a["chat_id"] == message.chat.id)]
        if len(remaining) == len(alerts):
            await message.answer("Алерт с таким id не найден.")
            return
        ctx.set(ALERTS_KEY, remaining)
        await message.answer("🗑 Алерт удалён.")

    return router


async def background(bot: Bot, ctx: PluginContext) -> None:
    while True:
        await asyncio.sleep(TICK)
        alerts = ctx.get(ALERTS_KEY, [])
        if not alerts:
            continue
        try:
            prices = await fetch_prices(ctx.services.http, [a["coin"] for a in alerts])
        except Exception:
            log.warning("price check failed, retrying next tick")
            continue
        fired_ids: set[str] = set()
        for alert in alerts:
            price = (prices.get(alert["coin"]) or {}).get("usd")
            if price is None or not is_triggered(alert["op"], alert["target"], price):
                continue
            fired_ids.add(alert["id"])
            try:
                await bot.send_message(
                    alert["chat_id"],
                    f"🔔 <b>{alert['symbol']}</b> {OP_TEXT[alert['op']]} {fmt_price(alert['target'])} $\n"
                    f"Сейчас: <b>{fmt_price(price)} $</b>",
                )
            except Exception:
                log.warning("could not deliver alert %s", alert["id"])
        if fired_ids:
            ctx.set(ALERTS_KEY, [a for a in ctx.get(ALERTS_KEY, []) if a["id"] not in fired_ids])


SPEC = PluginSpec(
    name="crypto_alerts",
    title="Крипто-алерты",
    icon="📉",
    description="Цены BTC, ETH и других монет, алерты на уровни и изменение за 24 часа.",
    build=build,
    commands=(("price", "Цены монет"), ("alert", "Создать алерт"), ("alerts", "Мои алерты")),
    background=background,
)
