import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..ui import card, hint, title
from .base import PluginContext, PluginSpec

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
MAX_HOPS = 8
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class UnsafeUrl(ValueError):
    pass


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrl("Допустимы только http и https ссылки")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as exc:
        raise UnsafeUrl("Домен не найден") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeUrl("Ссылка ведёт на внутренний адрес")


async def _follow(http: httpx.AsyncClient, url: str) -> tuple[list[str], httpx.Response]:
    chain = [url]
    for _ in range(MAX_HOPS):
        _check_host(url)
        resp = await http.get(url, follow_redirects=False, timeout=10)
        if resp.is_redirect and "location" in resp.headers:
            url = urljoin(url, resp.headers["location"])
            chain.append(url)
            continue
        return chain, resp
    raise UnsafeUrl("Слишком много редиректов")


def build(ctx: PluginContext) -> Router:
    router = Router(name="links")
    http = ctx.services.http

    @router.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            title("Ссылки", "🔗")
            + "\n• <code>/expand url</code> — пройти все редиректы\n"
            "• <code>/check url</code> — статус, сервер и заголовок страницы\n"
            "• Или просто пришлите ссылку — проверю её\n"
            + hint("Внутренние и приватные адреса заблокированы.")
        )

    async def _check(message: Message, url: str) -> None:
        status = await message.answer("⏳ Проверяю…")
        try:
            chain, resp = await _follow(http, url)
        except UnsafeUrl as exc:
            await status.edit_text(f"❌ {exc}")
            return
        except httpx.HTTPError as exc:
            await status.edit_text(f"❌ Ссылка не открылась: {type(exc).__name__}")
            return
        page_title = ""
        if "text/html" in resp.headers.get("content-type", ""):
            match = TITLE_RE.search(resp.text[:50_000])
            page_title = " ".join(match.group(1).split())[:200] if match else ""
        lines = [
            ("Статус", f"{resp.status_code} {'✅' if resp.status_code < 400 else '⚠️'}"),
            ("Сервер", resp.headers.get("server", "не указан")),
            ("Редиректов", str(len(chain) - 1)),
            ("Итоговый URL", str(resp.url)[:300]),
        ]
        if page_title:
            lines.append(("Заголовок", page_title))
        await status.edit_text(title("Проверка ссылки", "🔗") + "\n" + card(lines), disable_web_page_preview=True)

    async def _expand(message: Message, url: str) -> None:
        status = await message.answer("⏳ Раскрываю…")
        try:
            chain, _ = await _follow(http, url)
        except UnsafeUrl as exc:
            await status.edit_text(f"❌ {exc}")
            return
        except httpx.HTTPError as exc:
            await status.edit_text(f"❌ Ошибка: {type(exc).__name__}")
            return
        steps = "\n".join(f"{i}. {u}" for i, u in enumerate(chain, 1))
        await status.edit_text(title("Цепочка редиректов", "🔗") + f"\n{steps}", disable_web_page_preview=True)

    @router.message(Command("expand"))
    async def cmd_expand(message: Message, command: CommandObject) -> None:
        match = URL_RE.search(command.args or "")
        if not match:
            await message.answer("Пришлите ссылку: <code>/expand https://...</code>")
            return
        await _expand(message, match.group(0))

    @router.message(Command("check"))
    async def cmd_check(message: Message, command: CommandObject) -> None:
        match = URL_RE.search(command.args or "")
        if not match:
            await message.answer("Пришлите ссылку: <code>/check https://...</code>")
            return
        await _check(message, match.group(0))

    @router.message(F.text.regexp(URL_RE))
    async def on_link(message: Message) -> None:
        match = URL_RE.search(message.text or "")
        if match:
            await _check(message, match.group(0))

    return router


SPEC = PluginSpec(
    name="links",
    title="Проверка ссылок",
    icon="🔗",
    description="Раскрывает короткие ссылки, показывает цепочку редиректов и заголовок страницы.",
    build=build,
    commands=(("expand", "Раскрыть ссылку"), ("check", "Проверить ссылку")),
)
