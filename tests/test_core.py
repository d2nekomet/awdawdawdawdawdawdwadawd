import asyncio
import io
import json
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image

from franchise.billing import Billing
from franchise.config import Settings
from franchise.db import Database
from franchise.drive import DriveClient, DriveError
from franchise.payments import Settled, build_providers
from franchise.payments.cryptobot import CryptoBotProvider
from franchise.payments.stars import make_payload, parse_payload
from franchise.plugins import PLUGINS, PluginContext, Services
from franchise.plugins.images import _process
from franchise.plugins.links import UnsafeUrl, _check_host
from franchise.plugins.reminders import parse as parse_reminder
from franchise.plugins.scheduler import parse as parse_schedule
from franchise.plugins.text_tools import _slug
from franchise.plugins.tiktok import URL_RE as TIKTOK_RE
from franchise.plugins.qr import _render as render_qr

ADMIN = 7161045475


def make_settings(tmp: Path, **overrides) -> Settings:
    base = dict(
        hub_token="1:test",
        admin_ids=frozenset({ADMIN}),
        data_dir=tmp,
        sub_days=30,
        stars_price=100,
        enabled_payments=("stars",),
        cryptobot_token="",
        cryptobot_testnet=True,
        cryptobot_asset="USDT",
        cryptobot_amount="1",
        max_bots_per_user=3,
        drive_upload_url="",
        drive_api_token="",
        translate_url="http://translate.test",
        translate_api_key="",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.sqlite3")
    yield database
    database.close()


@pytest.fixture
def billing(db, tmp_path):
    settings = make_settings(tmp_path)
    return Billing(db, settings, build_providers(settings, db))


# billing and subscriptions

def test_admin_always_has_access(billing):
    assert billing.has_access(ADMIN)


def test_new_user_has_no_access_until_paid(billing):
    assert not billing.has_access(42)


def test_grant_extends_subscription_once_per_charge(billing):
    settled = Settled("stars", "charge-1", 42, 30, "100", "XTR")
    first = billing.grant(settled)
    second = billing.grant(settled)
    assert first > time.time()
    assert second == 0
    assert billing.has_access(42)
    assert billing.db.subscription_expires(42) == first


def test_grant_stacks_on_active_subscription(billing):
    first = billing.grant(Settled("stars", "a", 42, 30, "100", "XTR"))
    second = billing.grant(Settled("stars", "b", 42, 30, "100", "XTR"))
    assert second - first == 30 * 86400


def test_pending_payment_is_settled_only_once(billing):
    billing.db.create_pending_payment("cryptobot", "inv-1", 42, 30, "1", "USDT")
    settled = Settled("cryptobot", "inv-1", 42, 30, "1", "USDT")
    assert billing.grant(settled) > 0
    assert billing.grant(settled) == 0


def test_revoke_removes_access(billing):
    billing.grant(Settled("stars", "x", 42, 30, "100", "XTR"))
    billing.db.revoke_subscription(42)
    assert not billing.has_access(42)


# stars payload

def test_stars_payload_roundtrip():
    payload = make_payload(42, 30)
    assert parse_payload(payload) == (42, 30)


@pytest.mark.parametrize("bad", ["", "stars:1:2", "other:1:2:x", "stars:a:b:c"])
def test_stars_payload_rejects_garbage(bad):
    assert parse_payload(bad) is None


# cryptobot provider with a mocked Crypto Pay API

class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def _cryptobot(db, handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CryptoBotProvider(
        token="tok", db=db, http=http, asset="USDT", amount="1", testnet=True
    )


def test_cryptobot_start_creates_pending_invoice(db):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers["Crypto-Pay-API-Token"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "ok": True,
            "result": {"invoice_id": 777, "bot_invoice_url": "https://t.me/CryptoBot?start=IV777"},
        })

    provider = _cryptobot(db, handler)
    bot = FakeBot()
    asyncio.run(provider.start(bot, 42, 30))

    assert seen["url"].startswith("https://testnet-pay.crypt.bot/api/createInvoice")
    assert seen["token"] == "tok"
    assert seen["body"]["asset"] == "USDT" and seen["body"]["amount"] == "1"
    payment = db.get_payment("cryptobot", "777")
    assert payment and payment.status == "pending" and payment.user_id == 42
    assert len(bot.messages) == 1 and bot.messages[0][0] == 42


def test_cryptobot_poll_returns_paid_and_expires_stale(db):
    db.create_pending_payment("cryptobot", "1", 42, 30, "1", "USDT")
    db.create_pending_payment("cryptobot", "2", 43, 30, "1", "USDT")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["invoice_ids"] == "1,2"
        return httpx.Response(200, json={
            "ok": True,
            "result": {"items": [
                {"invoice_id": 1, "status": "paid"},
                {"invoice_id": 2, "status": "expired"},
            ]},
        })

    provider = _cryptobot(db, handler)
    settled = asyncio.run(provider.poll())
    assert [s.external_id for s in settled] == ["1"]
    assert settled[0].user_id == 42 and settled[0].days == 30
    assert db.get_payment("cryptobot", "2").status == "expired"


def test_cryptobot_api_error_raises(db):
    def handler(request):
        return httpx.Response(200, json={"ok": False, "error": {"name": "UNAUTHORIZED"}})

    provider = _cryptobot(db, handler)
    with pytest.raises(RuntimeError):
        asyncio.run(provider._call("getMe"))


def test_providers_reject_unknown_and_require_token(tmp_path, db):
    with pytest.raises(RuntimeError):
        build_providers(make_settings(tmp_path, enabled_payments=("stars", "nope")), db)
    with pytest.raises(RuntimeError):
        build_providers(make_settings(tmp_path, enabled_payments=("cryptobot",), cryptobot_token=""), db)


# drive client

def test_drive_upload_returns_url(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        assert b'filename="a.txt"' in request.content
        return httpx.Response(200, json={"url": "https://drive.unlim-projects.lol/f/abc"})

    client = DriveClient("https://drive.test/upload", "secret", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    url = asyncio.run(client.upload("a.txt", b"hello", "text/plain"))
    assert url == "https://drive.unlim-projects.lol/f/abc"


def test_drive_requires_configuration():
    client = DriveClient("", "", httpx.AsyncClient())
    with pytest.raises(DriveError):
        asyncio.run(client.upload("a.txt", b"x"))


# plugin helpers

def test_tiktok_url_detection():
    assert TIKTOK_RE.search("смотри https://vm.tiktok.com/ZMabc123/ классно")
    assert TIKTOK_RE.search("https://www.tiktok.com/@user/video/123")
    assert not TIKTOK_RE.search("https://example.com/tiktok")


def test_reminder_parsing():
    assert parse_reminder("10m выпить воду") == (600, "выпить воду")
    assert parse_reminder("2h  позвонить") == (7200, "позвонить")
    assert parse_reminder("без времени") is None


def test_schedule_parsing_uses_moscow_time():
    parsed = parse_schedule("2030-01-02 18:30 Привет")
    assert parsed is not None
    at, text = parsed
    assert text == "Привет"
    assert time.gmtime(at).tm_hour == 15  # 18:30 МСК = 15:30 UTC
    assert parse_schedule("2030-13-40 99:99 x") is None


def test_slug():
    assert _slug("Hello World 2026") == "hello-world-2026"
    assert _slug("Crème Brûlée") == "creme-brulee"


def test_link_guard_blocks_internal_addresses():
    for url in ("http://127.0.0.1/admin", "http://10.0.0.5", "http://169.254.169.254/latest", "file:///etc/passwd"):
        with pytest.raises(UnsafeUrl):
            _check_host(url)


def test_qr_renders_png():
    png = render_qr("https://example.com")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_compression_produces_jpeg():
    src = Image.new("RGB", (3000, 2000), (200, 80, 40))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    data, (w, h) = _process(buf.getvalue(), grayscale=True)
    assert data[:2] == b"\xff\xd8"
    assert max(w, h) <= 1600


# plugin registry and wiring

def test_fifteen_plugins_registered():
    assert len(PLUGINS) == 15
    for name, spec in PLUGINS.items():
        assert spec.name == name
        assert spec.title and spec.icon and spec.description


def test_every_plugin_builds_a_router(db, tmp_path):
    services = Services(make_settings(tmp_path), db, DriveClient("", "", httpx.AsyncClient()), httpx.AsyncClient())
    from aiogram import Router

    for name, spec in PLUGINS.items():
        router = spec.build(PluginContext(services, ADMIN, name))
        assert isinstance(router, Router), name


def test_plugin_storage_is_isolated_per_owner(db, tmp_path):
    services = Services(make_settings(tmp_path), db, DriveClient("", "", httpx.AsyncClient()), httpx.AsyncClient())
    a = PluginContext(services, 1, "notes")
    b = PluginContext(services, 2, "notes")
    a.set("k", "va")
    assert b.get("k") is None
    assert a.get("k") == "va"
