import time

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import card, hint, title
from .base import PluginContext, PluginSpec

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
CACHE_TTL = 3600
_cache: dict = {"at": 0.0, "rates": {}}


async def _rates(http: httpx.AsyncClient) -> dict[str, tuple[float, int, str]]:
    if time.time() - _cache["at"] < CACHE_TTL and _cache["rates"]:
        return _cache["rates"]
    resp = await http.get(CBR_URL, timeout=15)
    resp.raise_for_status()
    rates = {"RUB": (1.0, 1, "Российский рубль")}
    for code, item in resp.json()["Valute"].items():
        rates[code] = (item["Value"], item["Nominal"], item["Name"])
    _cache.update(at=time.time(), rates=rates)
    return rates


def _rub_per_unit(rates: dict, code: str) -> float:
    value, nominal, _ = rates[code]
    return value / nominal


def build(ctx: PluginContext) -> Router:
    router = Router(name="currency")
    http = ctx.services.http

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Курсы валют", "💱")
            + "\n• <code>/rate usd</code> — курс к рублю по ЦБ РФ\n"
            "• <code>/conv 100 usd eur</code> — конвертация\n"
            + hint("Данные: Банк России, обновляются раз в час.")
        )

    @router.message(Command("rate"))
    async def cmd_rate(message: Message, command: CommandObject) -> None:
        code = (command.args or "usd").strip().upper()
        try:
            rates = await _rates(http)
        except httpx.HTTPError:
            await message.answer("❌ Не удалось получить курсы ЦБ. Попробуйте позже.")
            return
        if code not in rates:
            await message.answer(f"Валюта {code} не найдена. Пример: <code>/rate usd</code>")
            return
        per_unit = _rub_per_unit(rates, code)
        name = rates[code][2]
        await message.answer(
            title(f"{code} · {name}", "💱")
            + "\n"
            + card([("Курс", f"{per_unit:.4f} ₽ за 1 единицу")]),
        )

    @router.message(Command("conv"))
    async def cmd_conv(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) != 3:
            await message.answer("Формат: <code>/conv 100 usd eur</code>")
            return
        try:
            amount = float(parts[0].replace(",", "."))
        except ValueError:
            await message.answer("Сумма должна быть числом.")
            return
        src, dst = parts[1].upper(), parts[2].upper()
        try:
            rates = await _rates(http)
        except httpx.HTTPError:
            await message.answer("❌ Не удалось получить курсы ЦБ. Попробуйте позже.")
            return
        if src not in rates or dst not in rates:
            await message.answer("Не знаю одну из валют. Список: /rate <код>")
            return
        result = amount * _rub_per_unit(rates, src) / _rub_per_unit(rates, dst)
        await message.answer(f"💱 <b>{amount:,.2f} {src}</b> = <b>{result:,.4f} {dst}</b>".replace(",", " "))

    return router


SPEC = PluginSpec(
    name="currency",
    title="Курсы валют",
    icon="💱",
    description="Курсы валют ЦБ РФ и конвертер между валютами.",
    build=build,
    commands=(("rate", "Курс валюты"), ("conv", "Конвертер")),
)
