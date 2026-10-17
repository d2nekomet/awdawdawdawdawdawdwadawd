import asyncio
import logging

import httpx
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from franchise.billing import Billing
from franchise.config import Settings
from franchise.db import Database
from franchise.drive import DriveClient
from franchise.hub import build_hub
from franchise.payments import build_providers
from franchise.plugins import Services
from franchise.runtime import BotRuntime

HUB_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="catalog", description="Каталог инструментов"),
    BotCommand(command="newbot", description="Создать бота"),
    BotCommand(command="mybots", description="Мои боты"),
    BotCommand(command="subscribe", description="Подписка"),
    BotCommand(command="help", description="Помощь"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if not settings.hub_token:
        raise SystemExit("HUB_BOT_TOKEN не задан (см. .env.example)")
    if not settings.admin_ids:
        raise SystemExit("ADMIN_IDS пуст")

    db = Database(settings.db_path)
    http = httpx.AsyncClient(timeout=20)
    providers = build_providers(settings, db)
    billing = Billing(db, settings, providers)
    services = Services(
        settings=settings,
        db=db,
        drive=DriveClient(settings.drive_upload_url, settings.drive_api_token, http),
        http=http,
    )
    runtime = BotRuntime(services, billing)

    hub = Bot(
        settings.hub_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    me = await hub.get_me()
    runtime.set_hub_link(f"@{me.username}")
    await hub.set_my_commands(HUB_COMMANDS)
    await hub.set_my_short_description("Фабрика ботов: инструменты за одну подписку")

    dp = build_hub(services, billing, runtime)
    await runtime.start_all()
    poller = asyncio.create_task(billing.run_pollers(hub), name="billing-pollers")
    logging.getLogger(__name__).info("hub @%s is up", me.username)

    try:
        await dp.start_polling(hub, handle_signals=True, allowed_updates=dp.resolve_used_update_types())
    finally:
        poller.cancel()
        await runtime.shutdown()
        for provider in providers.values():
            await provider.aclose()
        await hub.session.close()
        await http.aclose()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
