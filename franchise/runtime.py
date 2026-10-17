import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand, CallbackQuery, Message, TelegramObject

from .billing import Billing
from .db import ChildBot
from .plugins import PLUGINS, PluginContext, Services

log = logging.getLogger(__name__)

RESTART_DELAY = 10


class OwnerGate(BaseMiddleware):
    """Бот работает, пока у владельца активна подписка. Пользователи бота ничего не платят."""

    def __init__(self, billing: Billing, owner_id: int, hub_link: str):
        self.billing = billing
        self.owner_id = owner_id
        self.hub_link = hub_link

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self.billing.has_access(self.owner_id):
            return await handler(event, data)
        text = (
            "⏸ <b>Бот временно не работает</b>\n"
            f"Владелец не продлил подписку. Заходите позже или напишите в {self.hub_link}."
        )
        if isinstance(event, CallbackQuery):
            await event.answer("Бот на паузе", show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text)
        return None


class BotRuntime:
    """Запускает каждого дочернего бота в собственном Dispatcher со своим токеном."""

    def __init__(self, services: Services, billing: Billing):
        self.services = services
        self.billing = billing
        self.hub_link = "главного бота"
        self._tasks: dict[int, list[asyncio.Task]] = {}
        self._sessions: dict[int, Bot] = {}

    def set_hub_link(self, link: str) -> None:
        self.hub_link = link

    async def start_all(self) -> None:
        for row in self.services.db.active_child_bots():
            try:
                await self.start(row)
            except Exception:
                log.exception("failed to start child bot %s", row.id)

    async def start(self, row: ChildBot) -> None:
        if row.id in self._tasks:
            return
        spec = PLUGINS[row.plugin]
        bot = Bot(row.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
        ctx = PluginContext(services=self.services, owner_id=row.owner_id, plugin=spec.name)

        router = Router(name=f"child-{row.id}")
        gate = OwnerGate(self.billing, row.owner_id, self.hub_link)
        router.message.outer_middleware(gate)
        router.callback_query.outer_middleware(gate)
        if spec.owner_only:
            router.message.filter(F.from_user.id == row.owner_id)
            router.callback_query.filter(F.from_user.id == row.owner_id)
        router.include_router(spec.build(ctx))

        dp = Dispatcher()
        dp.include_router(router)

        try:
            await bot.set_my_commands(
                [BotCommand(command="start", description="Начать работу")]
                + [BotCommand(command=c, description=d) for c, d in spec.commands]
            )
            await bot.set_my_short_description(spec.description[:120])
        except Exception:
            log.warning("could not set profile for child bot %s", row.username)

        self._sessions[row.id] = bot
        tasks = [asyncio.create_task(self._supervise(row, bot, dp), name=f"poll-{row.id}")]
        if spec.background:
            tasks.append(asyncio.create_task(spec.background(bot, ctx), name=f"bg-{row.id}"))
        self._tasks[row.id] = tasks
        log.info("started @%s (%s) for owner %s", row.username, spec.name, row.owner_id)

    async def _supervise(self, row: ChildBot, bot: Bot, dp: Dispatcher) -> None:
        while True:
            try:
                await dp.start_polling(
                    bot,
                    handle_signals=False,
                    allowed_updates=dp.resolve_used_update_types(),
                )
                return
            except asyncio.CancelledError:
                raise
            except TelegramUnauthorizedError:
                log.error("token of @%s was revoked, deactivating", row.username)
                self.services.db.deactivate_child_bot(row.id)
                return
            except Exception:
                log.exception("polling @%s crashed, restarting", row.username)
                await asyncio.sleep(RESTART_DELAY)

    async def stop(self, bot_id: int) -> None:
        for task in self._tasks.pop(bot_id, []):
            task.cancel()
        bot = self._sessions.pop(bot_id, None)
        if bot:
            await bot.session.close()
        self.services.db.deactivate_child_bot(bot_id)

    async def shutdown(self) -> None:
        for bot_id in list(self._tasks):
            for task in self._tasks.pop(bot_id, []):
                task.cancel()
        for bot in self._sessions.values():
            await bot.session.close()
        self._sessions.clear()

    def running(self, bot_id: int) -> bool:
        return bot_id in self._tasks

