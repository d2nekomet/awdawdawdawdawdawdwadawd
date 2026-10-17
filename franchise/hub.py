import logging
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    KeyboardButtonRequestManagedBot,
    ManagedBotUpdated,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from .billing import Billing, format_ts
from .payments import Settled
from .payments.stars import CURRENCY as STARS_CURRENCY
from .payments.stars import PAYLOAD_PREFIX as STARS_PREFIX
from .payments.stars import parse_payload as parse_stars_payload
from .plugins import PLUGINS, Services
from .runtime import BotRuntime
from .ui import card, hint, keyboard, title

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
SCOPE = "hub"
REQUEST_ID = 1


def _pending_key(user_id: int) -> str:
    return f"pending:{user_id}"


def build_hub(services: Services, billing: Billing, runtime: BotRuntime) -> Dispatcher:
    db = services.db
    settings = services.settings
    providers = billing.providers
    router = Router(name="hub")
    dp = Dispatcher()
    dp.include_router(router)

    def pending_plugin(user_id: int) -> str | None:
        return db.kv_get(SCOPE, _pending_key(user_id))

    def set_pending(user_id: int, plugin: str | None) -> None:
        if plugin is None:
            db.kv_delete(SCOPE, _pending_key(user_id))
        else:
            db.kv_set(SCOPE, _pending_key(user_id), plugin)

    def status_line(user_id: int) -> str:
        if billing.is_admin(user_id):
            return "👑 Администратор — полный доступ"
        until = billing.expires_text(user_id)
        if until:
            return f"✅ Подписка активна до <b>{until}</b>"
        return "🔒 Подписка не активна — оплатите вход, и все боты франшизы будут бесплатны"

    def home(user_id: int) -> tuple[str, object]:
        bots = len(db.child_bots_of(user_id))
        text = (
            title("Bot Franchise", "🤖")
            + f"\n{status_line(user_id)}\n\n"
            + card([("Ваши боты", str(bots)), ("Инструментов", str(len(PLUGINS)))])
        )
        kb = keyboard(
            rows=[
                [("📦 Каталог", "cat"), ("🤖 Создать бота", "new")],
                [("🗂 Мои боты", "mybots"), ("💳 Подписка", "sub")],
                [("❓ Помощь", "help")],
            ]
        )
        return text, kb

    def catalog(prefix: str) -> tuple[str, object]:
        rows = []
        items = list(PLUGINS.values())
        for i in range(0, len(items), 2):
            rows.append(
                [(f"{p.icon} {p.title}", f"{prefix}:{p.name}") for p in items[i : i + 2]]
            )
        rows.append([("⬅️ В меню", "home")])
        text = title("Каталог инструментов", "📦") + f"\n{len(items)} ботов. Каждый — отдельный Telegram-бот."
        return text, keyboard(rows=rows)

    def plugin_card(name: str) -> tuple[str, object]:
        spec = PLUGINS[name]
        cmds = "\n".join(f"• /{c} — {d}" for c, d in spec.commands) or "• Работает без команд"
        text = (
            title(spec.title, spec.icon)
            + f"\n{spec.description}\n\n<b>Команды</b>\n{cmds}"
            + ("\n\n" + hint("Только для владельца бота.") if spec.owner_only else "")
        )
        kb = keyboard(rows=[[("➕ Создать бота", f"new:{name}")], [("⬅️ К каталогу", "cat")]])
        return text, kb

    def subscription() -> tuple[str, object]:
        lines = []
        rows = []
        for name, provider in providers.items():
            if name == "stars":
                price = f"{settings.stars_price} ⭐"
            else:
                price = f"{settings.cryptobot_amount} {settings.cryptobot_asset}"
            lines.append(f"{provider.title} — <b>{price}</b>")
            rows.append([(f"Оплатить · {provider.title}", f"pay:{name}")])
        rows.append([("⬅️ В меню", "home")])
        text = (
            title("Подписка", "💳")
            + f"\nСрок: <b>{settings.sub_days} дней</b>. Внутри — все боты франшизы без доплат.\n\n"
            + "\n".join(lines)
            + "\n\n"
            + hint("Способ оплаты добавляется в payments/__init__.py и настраивается в .env.")
        )
        return text, keyboard(rows=rows)

    def paywall() -> tuple[str, object]:
        text, kb = subscription()
        return "🔒 <b>Нужна подписка</b>\nОплатите вход один раз — дальше все боты бесплатны.\n\n" + text, kb

    async def show(target: Message | CallbackQuery, text: str, kb) -> None:
        if isinstance(target, CallbackQuery):
            try:
                await target.message.edit_text(text, reply_markup=kb)
            except TelegramAPIError:
                await target.message.answer(text, reply_markup=kb)
            await target.answer()
        else:
            await target.answer(text, reply_markup=kb)

    # navigation

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        db.touch_user(message.from_user.id)
        set_pending(message.from_user.id, None)
        text, kb = home(message.from_user.id)
        await message.answer(text, reply_markup=kb)

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(_help_text())

    @router.callback_query(F.data == "home")
    async def cb_home(query: CallbackQuery) -> None:
        text, kb = home(query.from_user.id)
        await show(query, text, kb)

    @router.callback_query(F.data == "help")
    async def cb_help(query: CallbackQuery) -> None:
        await show(query, _help_text(), keyboard(rows=[[("⬅️ В меню", "home")]]))

    @router.message(Command("catalog"))
    async def cmd_catalog(message: Message) -> None:
        text, kb = catalog("cat")
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "cat")
    async def cb_catalog(query: CallbackQuery) -> None:
        text, kb = catalog("cat")
        await show(query, text, kb)

    @router.callback_query(F.data.startswith("cat:"))
    async def cb_plugin(query: CallbackQuery) -> None:
        name = query.data.split(":", 1)[1]
        if name not in PLUGINS:
            await query.answer("Инструмент не найден", show_alert=True)
            return
        text, kb = plugin_card(name)
        await show(query, text, kb)

    # creating bots

    @router.message(Command("newbot"))
    async def cmd_newbot(message: Message) -> None:
        text, kb = catalog("new")
        if not billing.has_access(message.from_user.id):
            text, kb = paywall()
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "new")
    async def cb_new_menu(query: CallbackQuery) -> None:
        if not billing.has_access(query.from_user.id):
            text, kb = paywall()
        else:
            text, kb = catalog("new")
        await show(query, text, kb)

    @router.callback_query(F.data.startswith("new:"))
    async def cb_new(query: CallbackQuery) -> None:
        user_id = query.from_user.id
        name = query.data.split(":", 1)[1]
        if name not in PLUGINS:
            await query.answer("Инструмент не найден", show_alert=True)
            return
        if not billing.has_access(user_id):
            text, kb = paywall()
            await show(query, text, kb)
            return
        if not billing.is_admin(user_id) and len(db.child_bots_of(user_id)) >= settings.max_bots_per_user:
            await query.answer(f"Лимит {settings.max_bots_per_user} ботов на аккаунт", show_alert=True)
            return
        set_pending(user_id, name)
        spec = PLUGINS[name]
        request_kb = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text="🤖 Создать бота в Telegram",
                        request_managed_bot=KeyboardButtonRequestManagedBot(
                            request_id=REQUEST_ID,
                            suggested_name=f"{spec.title} bot"[:64],
                        ),
                    )
                ],
                [KeyboardButton(text="✍️ У меня уже есть токен")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
            input_field_placeholder="Нажмите кнопку ниже",
        )
        await query.message.answer(
            title(f"Новый бот: {spec.title}", spec.icon)
            + "\nНажмите кнопку ниже — Telegram создаст бота прямо здесь, без BotFather.\n"
            + hint("Или пришлите токен от BotFather, если бот уже создан."),
            reply_markup=request_kb,
        )
        await query.answer()

    @router.message(F.text == "✍️ У меня уже есть токен")
    async def on_have_token(message: Message) -> None:
        await message.answer("Пришлите токен бота от @BotFather одним сообщением.", reply_markup=ReplyKeyboardRemove())

    @router.managed_bot()
    async def on_managed_bot(event: ManagedBotUpdated, bot: Bot) -> None:
        creator = event.user.id
        plugin = pending_plugin(creator)
        if plugin is None:
            await bot.send_message(creator, "Сначала выберите инструмент: /catalog")
            return
        token = await bot.get_managed_bot_token(event.bot_user.id)
        await _register(bot, creator, token, plugin, message_chat=creator)

    @router.message(F.text.regexp(TOKEN_RE))
    async def on_token(message: Message, bot: Bot) -> None:
        user_id = message.from_user.id
        plugin = pending_plugin(user_id)
        if plugin is None:
            await message.answer("Сначала выберите инструмент: /catalog", reply_markup=ReplyKeyboardRemove())
            return
        await _register(bot, user_id, message.text.strip(), plugin, message_chat=user_id)

    async def _register(bot: Bot, owner_id: int, token: str, plugin: str, message_chat: int) -> None:
        if not billing.has_access(owner_id):
            text, kb = paywall()
            await bot.send_message(message_chat, text, reply_markup=kb)
            return
        if not billing.is_admin(owner_id) and len(db.child_bots_of(owner_id)) >= settings.max_bots_per_user:
            await bot.send_message(message_chat, f"Лимит {settings.max_bots_per_user} ботов на аккаунт.")
            return
        if db.child_bot_by_token(token):
            await bot.send_message(message_chat, "Этот бот уже подключён.")
            return
        try:
            async with Bot(token=token) as child:
                child_me = await child.get_me()
        except TelegramAPIError:
            await bot.send_message(message_chat, "❌ Токен не принят Telegram. Проверьте его в @BotFather.")
            return
        row_id = db.add_child_bot(owner_id, token, child_me.username or str(child_me.id), plugin)
        row = db.find_child_bot(row_id)
        await runtime.start(row)
        set_pending(owner_id, None)
        spec = PLUGINS[plugin]
        await bot.send_message(
            message_chat,
            title("Бот запущен", "🚀")
            + "\n"
            + card([("Инструмент", f"{spec.icon} {spec.title}"), ("Бот", f"@{child_me.username}")])
            + f"\n\nОткройте <a href=\"https://t.me/{child_me.username}\">@{child_me.username}</a> и нажмите Start.",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(Command("addtoken"))
    async def cmd_addtoken(message: Message, command: CommandObject, bot: Bot) -> None:
        token = (command.args or "").strip()
        if not TOKEN_RE.match(token):
            await message.answer("Формат: <code>/addtoken 123456:ABC...</code>")
            return
        plugin = pending_plugin(message.from_user.id)
        if plugin is None:
            await message.answer("Сначала выберите инструмент: /catalog")
            return
        await _register(bot, message.from_user.id, token, plugin, message_chat=message.chat.id)

    @router.message(Command("mybots"))
    async def cmd_mybots(message: Message) -> None:
        text, kb = _mybots(message.from_user.id)
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "mybots")
    async def cb_mybots(query: CallbackQuery) -> None:
        text, kb = _mybots(query.from_user.id)
        await show(query, text, kb)

    def _mybots(user_id: int) -> tuple[str, object]:
        bots = db.child_bots_of(user_id)
        if not bots:
            return (
                title("Мои боты", "🗂") + "\nПока пусто. Создайте первого бота из каталога.",
                keyboard(rows=[[("📦 Каталог", "cat")], [("⬅️ В меню", "home")]]),
            )
        lines = []
        rows = []
        for b in bots:
            spec = PLUGINS[b.plugin]
            state = "🟢" if runtime.running(b.id) else "⚪"
            lines.append(f"{state} {spec.icon} <b>{spec.title}</b> — @{b.username}")
            rows.append([(f"⏹ Остановить @{b.username}", f"bot:stop:{b.id}")])
        rows.append([("⬅️ В меню", "home")])
        return title("Мои боты", "🗂") + "\n" + "\n".join(lines), keyboard(rows=rows)

    @router.callback_query(F.data.startswith("bot:stop:"))
    async def cb_stop(query: CallbackQuery) -> None:
        bot_id = int(query.data.rsplit(":", 1)[1])
        row = db.find_child_bot(bot_id)
        if row is None or row.owner_id != query.from_user.id:
            await query.answer("Бот не найден", show_alert=True)
            return
        await runtime.stop(bot_id)
        text, kb = _mybots(query.from_user.id)
        await show(query, text + f"\n\n⏹ @{row.username} остановлен.", kb)

    # subscription and payments

    @router.message(Command("subscribe"))
    async def cmd_subscribe(message: Message) -> None:
        text, kb = subscription()
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "sub")
    async def cb_sub(query: CallbackQuery) -> None:
        text, kb = subscription()
        await show(query, text, kb)

    @router.callback_query(F.data.startswith("pay:"))
    async def cb_pay(query: CallbackQuery, bot: Bot) -> None:
        name = query.data.split(":", 1)[1]
        provider = providers.get(name)
        if provider is None:
            await query.answer("Этот способ оплаты выключен", show_alert=True)
            return
        try:
            await provider.start(bot, query.from_user.id, settings.sub_days)
        except Exception as exc:
            log.exception("payment start failed: %s", name)
            await query.answer(f"Не удалось создать счёт: {str(exc)[:120]}", show_alert=True)
            return
        await query.answer("Счёт отправлен в чат")

    @router.pre_checkout_query()
    async def on_pre_checkout(query: PreCheckoutQuery) -> None:
        parsed = parse_stars_payload(query.invoice_payload)
        ok = (
            "stars" in providers
            and parsed is not None
            and parsed[0] == query.from_user.id
            and query.currency == STARS_CURRENCY
            and query.total_amount == settings.stars_price
        )
        await query.answer(ok=ok, error_message=None if ok else "Счёт устарел. Создайте новый в /subscribe")

    @router.message(F.successful_payment)
    async def on_paid(message: Message) -> None:
        sp = message.successful_payment
        parsed = parse_stars_payload(sp.invoice_payload)
        if parsed is None or not sp.invoice_payload.startswith(STARS_PREFIX):
            return
        user_id, days = parsed
        expires = billing.grant(
            Settled("stars", sp.telegram_payment_charge_id, user_id, days, str(sp.total_amount), sp.currency)
        )
        if expires:
            await message.answer(
                title("Оплата получена", "✅")
                + f"\nПодписка активна до <b>{format_ts(expires)}</b>.\nВсе боты франшизы теперь бесплатны."
                + f"\n\n{hint('Чек: ' + sp.telegram_payment_charge_id)}"
            )

    # admin

    is_admin = F.from_user.id.in_(settings.admin_ids)

    @router.message(Command("admin"), is_admin)
    async def cmd_admin(message: Message) -> None:
        s = db.stats()
        await message.answer(
            title("Панель администратора", "👑")
            + "\n"
            + card([
                ("Пользователей", str(s["users"])),
                ("Активных подписок", str(s["active_subs"])),
                ("Ботов запущено", str(s["child_bots"])),
                ("Оплат", str(s["paid_payments"])),
            ])
            + "\n\n<code>/grant id дни</code> · <code>/revoke id</code>\n<code>/refund charge_id</code>"
        )

    @router.message(Command("grant"), is_admin)
    async def cmd_grant(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await message.answer("Формат: <code>/grant 123456 30</code>")
            return
        user_id, days = int(parts[0]), int(parts[1])
        expires = db.extend_subscription(user_id, days)
        await message.answer(f"✅ Подписка {user_id} до {format_ts(expires)}")
        try:
            await message.bot.send_message(user_id, f"🎁 Вам выдана подписка до <b>{format_ts(expires)}</b>.")
        except TelegramAPIError:
            pass

    @router.message(Command("revoke"), is_admin)
    async def cmd_revoke(message: Message, command: CommandObject) -> None:
        target = (command.args or "").strip()
        if not target.isdigit():
            await message.answer("Формат: <code>/revoke 123456</code>")
            return
        db.revoke_subscription(int(target))
        await message.answer(f"⛔️ Подписка {target} отозвана.")

    @router.message(Command("refund"), is_admin)
    async def cmd_refund(message: Message, command: CommandObject) -> None:
        charge_id = (command.args or "").strip()
        payment = db.get_payment("stars", charge_id)
        if payment is None or payment.status != "paid":
            await message.answer("Оплата не найдена или уже возвращена.")
            return
        try:
            await message.bot.refund_star_payment(user_id=payment.user_id, telegram_payment_charge_id=charge_id)
        except TelegramAPIError as exc:
            await message.answer(f"❌ Telegram отказал: {exc.message}")
            return
        db.set_payment_status("stars", charge_id, "refunded")
        db.revoke_subscription(payment.user_id)
        await message.answer(f"↩️ Звёзды за {charge_id} возвращены, подписка {payment.user_id} отозвана.")

    @router.message(Command("myid"))
    async def cmd_myid(message: Message) -> None:
        await message.answer(f"Ваш ID: <code>{message.from_user.id}</code>")

    @router.message(F.text)
    async def fallback(message: Message) -> None:
        if not message.text.startswith("/"):
            text, kb = home(message.from_user.id)
            await message.answer(text, reply_markup=kb)

    return dp


def _help_text() -> str:
    return (
        title("Помощь", "❓")
        + "\n<b>Как это работает</b>\n"
        "1. Оплатите подписку один раз — Stars или криптой.\n"
        "2. Выберите инструмент в /catalog.\n"
        "3. Создайте бота в один клик — он сразу работает.\n\n"
        "<b>Команды</b>\n"
        "/catalog — все инструменты\n/newbot — создать бота\n/mybots — ваши боты\n"
        "/subscribe — подписка\n/myid — ваш ID"
    )

