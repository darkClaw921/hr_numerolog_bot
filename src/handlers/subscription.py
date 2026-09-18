"""
Подписка: оффер с оплатой через Prodamus (/subscribe, кабинет → «Подписка»), статус,
отмена автопродления (кнопка в кабинете или /unsubscribe) и ручная выдача премиума
админом (/grant).

Премиум включается ТОЛЬКО по уведомлению Prodamus (см. src/payments/webhook.py) —
возврат пользователя на urlSuccess ничего не активирует.
"""
import logging
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.admin_mode import has_admin_rights, simulated_premium
from src.config import (
    BOT_USERNAME,
    PAYMENTS_ENABLED,
    PRODAMUS_TRIAL_DAYS,
    SUBSCRIPTION_FIRST_PAYMENT_RUB,
)
from src.db.models import BotUser
from src.db.repositories import PaymentIntentRepo, PaymentRepo, SubscriptionRepo, UserRepo
from src.formatting import edit_or_send
from src.keyboards import BACK_TO_CABINET_BUTTON, back_to_cabinet_keyboard
from src.payments.prodamus import build_payment_link, set_activity
from src.texts import (
    SUB_CANCEL_CONFIRM,
    SUB_CANCEL_DONE,
    SUB_CANCEL_FAILED,
    SUB_CANCEL_NOTHING,
    SUB_DISABLED_TEXT,
    SUB_OFFER_TEXT,
    SUB_OFFER_TRIAL_LINE,
    SUB_PAY_BUTTON,
    SUB_STATUS_ACTIVE,
    SUB_STATUS_CANCELLED,
    SUB_STATUS_INACTIVE,
    SUB_STATUS_MANUAL,
    SUB_STATUS_SIMULATED,
)

logger = logging.getLogger(__name__)
router = Router()


def _format_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value is not None else "—"


def _new_order_id(db_user: BotUser) -> str:
    """order_id принимается вебхуком, только если бот сам его выдал (см. payment_intents)."""
    return f"{db_user.id}-{uuid4().hex[:10]}"


CANCEL_BUTTON = InlineKeyboardButton(text="❌ Отменить подписку", callback_data="sub:ask")


def _screen_keyboard(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    """Клавиатура экрана подписки: переданные ряды + возврат в кабинет."""
    return InlineKeyboardMarkup(inline_keyboard=[*rows, [BACK_TO_CABINET_BUTTON]])


async def build_subscription_screen(
    db_user: BotUser,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Общий экран подписки: статус (с отменой) для активной, оффер с оплатой — для остальных."""
    simulated = simulated_premium(db_user.telegram_id)
    if simulated:
        return SUB_STATUS_SIMULATED, _screen_keyboard()
    sub = await _real_subscription(db_user, subscription_repo)
    if sub is not None and await subscription_repo.is_active(db_user.id):
        if sub is not None and sub.cancelled_at is not None:
            return SUB_STATUS_CANCELLED.format(expires=_format_date(sub.expires_at)), _screen_keyboard()
        if sub is not None and sub.prodamus_active:
            next_payment = sub.next_payment_at
            if next_payment is not None and next_payment.replace(tzinfo=None) <= datetime.now(timezone.utc).replace(tzinfo=None):
                # Списание просрочено (Prodamus повторяет попытки) — прошлую дату не показываем.
                next_payment = None
            text = SUB_STATUS_ACTIVE.format(
                expires=_format_date(sub.expires_at),
                next_payment=_format_date(next_payment),
            )
            return text, _screen_keyboard([CANCEL_BUTTON])
        # Без автопродления (ручная выдача или реферальный бонус) — отменять нечего.
        expires = _format_date(sub.expires_at) if sub and sub.expires_at else "бессрочно"
        return SUB_STATUS_MANUAL.format(expires=expires), _screen_keyboard()

    if not PAYMENTS_ENABLED:
        return SUB_DISABLED_TEXT, _screen_keyboard()

    if intent_repo is None:
        return SUB_STATUS_INACTIVE, _screen_keyboard()

    order_id = _new_order_id(db_user)
    # Сумма первого платежа — с учётом скидки подписки на первый месяц.
    await intent_repo.create(db_user.id, order_id, amount_rub=SUBSCRIPTION_FIRST_PAYMENT_RUB)
    link = build_payment_link(
        order_id=order_id,
        telegram_id=db_user.telegram_id,
        bot_username=BOT_USERNAME,
    )
    text = SUB_OFFER_TEXT
    if PRODAMUS_TRIAL_DAYS > 0:
        text += SUB_OFFER_TRIAL_LINE.format(days=PRODAMUS_TRIAL_DAYS)
    return text, _screen_keyboard([InlineKeyboardButton(text=SUB_PAY_BUTTON, url=link)])


@router.message(Command("subscribe"))
async def cmd_subscribe(
    message: Message,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo,
    db_user: BotUser,
):
    """Оффер с ссылкой на оплату либо статус уже активной подписки."""
    text, keyboard = await build_subscription_screen(db_user, subscription_repo, intent_repo)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "cab:sub")
async def cb_subscription(
    callback: CallbackQuery,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo,
    db_user: BotUser,
):
    """Экран подписки из кабинета (и с пейволла) — тот же, что у /subscribe."""
    await callback.answer()
    text, keyboard = await build_subscription_screen(db_user, subscription_repo, intent_repo)
    await edit_or_send(callback, text, keyboard)


async def _real_subscription(db_user: BotUser, subscription_repo: SubscriptionRepo):
    """
    Подписка из БД; в режиме проверки админа — как будто её нет, чтобы экраны
    и отмена не трогали настоящую подписку админа.
    """
    if simulated_premium(db_user.telegram_id) is not None:
        return None
    return await subscription_repo.get(db_user.id)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, отключить", callback_data="sub:cancel")],
            [InlineKeyboardButton(text="Нет, оставить", callback_data="sub:keep")],
        ]
    )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Отмена автопродления — с подтверждением, доступ до конца оплаченного периода."""
    sub = await _real_subscription(db_user, subscription_repo)
    if sub is None or not sub.prodamus_active:
        await message.answer(SUB_CANCEL_NOTHING)
        return
    await message.answer(SUB_CANCEL_CONFIRM, reply_markup=_confirm_keyboard())


@router.callback_query(F.data == "sub:ask")
async def cb_cancel_ask(callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Кнопка «Отменить подписку» в кабинете — то же подтверждение, что у /unsubscribe."""
    await callback.answer()
    sub = await _real_subscription(db_user, subscription_repo)
    if sub is None or not sub.prodamus_active:
        await edit_or_send(callback, SUB_CANCEL_NOTHING, back_to_cabinet_keyboard())
        return
    await edit_or_send(callback, SUB_CANCEL_CONFIRM, _confirm_keyboard())


@router.callback_query(F.data == "sub:keep")
async def cb_cancel_keep(
    callback: CallbackQuery,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo,
    db_user: BotUser,
):
    await callback.answer("Подписка сохранена")
    text, keyboard = await build_subscription_screen(db_user, subscription_repo, intent_repo)
    await edit_or_send(callback, text, keyboard)


@router.callback_query(F.data == "sub:cancel")
async def cb_cancel_subscription(
    callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser
):
    await callback.answer()
    sub = await _real_subscription(db_user, subscription_repo)
    if sub is None or not sub.prodamus_active:
        await edit_or_send(callback, SUB_CANCEL_NOTHING, back_to_cabinet_keyboard())
        return

    response = await set_activity(
        active_manager=False,
        subscription_id=sub.prodamus_subscription_id,
        customer_phone=sub.prodamus_customer_phone,
        customer_email=sub.prodamus_customer_email,
        tg_user_id=db_user.telegram_id,
    )
    if not response.get("ok"):
        await edit_or_send(callback, SUB_CANCEL_FAILED, back_to_cabinet_keyboard())
        return

    # Локально фиксируем сразу; подтверждающее уведомление Prodamus придёт следом.
    await subscription_repo.mark_cancelled(db_user.id)
    await edit_or_send(
        callback, SUB_CANCEL_DONE.format(expires=_format_date(sub.expires_at)), back_to_cabinet_keyboard()
    )


@router.message(Command("grant"))
async def cmd_grant(
    message: Message,
    command: CommandObject,
    user_repo: UserRepo,
    subscription_repo: SubscriptionRepo,
):
    """
    Ручная выдача премиума (только админ): /grant <telegram_id> [дней].
    Без указания дней — бессрочно.
    """
    if not has_admin_rights(message.from_user.id):
        await message.answer("⛔ Команда доступна только администраторам.")
        return

    args = (command.args or "").split()
    if not args:
        await message.answer("Использование: /grant &lt;telegram_id&gt; [дней]")
        return

    try:
        target_telegram_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else None
    except ValueError:
        await message.answer("❌ Неверные аргументы. Пример: /grant 123456789 30")
        return

    target_user = await user_repo.get_or_create(telegram_id=target_telegram_id)
    await subscription_repo.set_premium(target_user.id, is_premium=True, days=days)

    period = f"на {days} дн." if days else "бессрочно"
    await message.answer(f"✅ Премиум выдан пользователю {target_telegram_id} ({period}).")


@router.message(Command("payments"))
async def cmd_payments(
    message: Message,
    command: CommandObject,
    user_repo: UserRepo,
    payment_repo: PaymentRepo,
):
    """Журнал платежей пользователя (только админ): /payments <telegram_id>."""
    if not has_admin_rights(message.from_user.id):
        await message.answer("⛔ Команда доступна только администраторам.")
        return

    args = (command.args or "").split()
    if not args or not args[0].lstrip("-").isdigit():
        await message.answer("Использование: /payments &lt;telegram_id&gt;")
        return

    target = await user_repo.get_by_telegram_id(int(args[0]))
    if target is None:
        await message.answer("Пользователь не найден.")
        return

    items = await payment_repo.list_by_user(target.id, limit=10)
    if not items:
        await message.answer("Платежей нет.")
        return

    lines = [f"💳 <b>Платежи {args[0]}</b>\n"]
    for item in items:
        when = item.created_at.strftime("%d.%m.%Y %H:%M") if item.created_at else "—"
        lines.append(f"• {when} — {item.status or '—'} / {item.kind}, {item.amount_rub or '—'} ₽")
    await message.answer("\n".join(lines), parse_mode="HTML")
