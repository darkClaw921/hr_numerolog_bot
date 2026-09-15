"""
Подписка: оффер с оплатой через Prodamus (/subscribe), статус, отмена автопродления
(/unsubscribe) и ручная выдача премиума админом (/grant).

Премиум включается ТОЛЬКО по уведомлению Prodamus (см. src/payments/webhook.py) —
возврат пользователя на urlSuccess ничего не активирует.
"""
import logging
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.config import (
    ADMIN_USER_IDS,
    BOT_USERNAME,
    PAYMENTS_ENABLED,
    PRODAMUS_TRIAL_DAYS,
    SUBSCRIPTION_PRICE_RUB,
)
from src.db.models import BotUser
from src.db.repositories import PaymentIntentRepo, PaymentRepo, SubscriptionRepo, UserRepo
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
)

logger = logging.getLogger(__name__)
router = Router()


def _format_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value is not None else "—"


def _new_order_id(db_user: BotUser) -> str:
    """order_id принимается вебхуком, только если бот сам его выдал (см. payment_intents)."""
    return f"{db_user.id}-{uuid4().hex[:10]}"


async def render_subscription_screen(
    target: Message,
    db_user: BotUser,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo | None = None,
) -> None:
    """Общий экран подписки: статус для активной, оффер с кнопкой оплаты — для остальных."""
    sub = await subscription_repo.get(db_user.id)
    if await subscription_repo.is_active(db_user.id):
        if sub is not None and sub.cancelled_at is not None:
            await target.answer(
                SUB_STATUS_CANCELLED.format(expires=_format_date(sub.expires_at)),
                parse_mode="HTML",
            )
        else:
            await target.answer(
                SUB_STATUS_ACTIVE.format(
                    expires=_format_date(sub.expires_at) if sub else "—",
                    next_payment=_format_date(sub.next_payment_at) if sub else "—",
                ),
                parse_mode="HTML",
            )
        return

    if not PAYMENTS_ENABLED:
        await target.answer(SUB_DISABLED_TEXT, parse_mode="HTML")
        return

    if intent_repo is None:
        await target.answer(SUB_STATUS_INACTIVE, parse_mode="HTML")
        return

    order_id = _new_order_id(db_user)
    await intent_repo.create(db_user.id, order_id, amount_rub=SUBSCRIPTION_PRICE_RUB)
    link = build_payment_link(
        order_id=order_id,
        telegram_id=db_user.telegram_id,
        bot_username=BOT_USERNAME,
    )
    text = SUB_OFFER_TEXT
    if PRODAMUS_TRIAL_DAYS > 0:
        text += SUB_OFFER_TRIAL_LINE.format(days=PRODAMUS_TRIAL_DAYS)
    await target.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=SUB_PAY_BUTTON, url=link)]]
        ),
    )


@router.message(Command("subscribe"))
async def cmd_subscribe(
    message: Message,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo,
    db_user: BotUser,
):
    """Оффер с ссылкой на оплату либо статус уже активной подписки."""
    await render_subscription_screen(message, db_user, subscription_repo, intent_repo)


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Отмена автопродления — с подтверждением, доступ до конца оплаченного периода."""
    sub = await subscription_repo.get(db_user.id)
    if sub is None or not sub.prodamus_active:
        await message.answer(SUB_CANCEL_NOTHING)
        return
    await message.answer(
        SUB_CANCEL_CONFIRM,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Да, отключить", callback_data="sub:cancel")],
                [InlineKeyboardButton(text="Нет, оставить", callback_data="sub:keep")],
            ]
        ),
    )


@router.callback_query(F.data == "sub:keep")
async def cb_cancel_keep(callback: CallbackQuery):
    await callback.answer("Подписка сохранена")
    await callback.message.answer("Ок, подписка остаётся активной.")


@router.callback_query(F.data == "sub:cancel")
async def cb_cancel_subscription(
    callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser
):
    await callback.answer()
    sub = await subscription_repo.get(db_user.id)
    if sub is None or not sub.prodamus_active:
        await callback.message.answer(SUB_CANCEL_NOTHING)
        return

    response = await set_activity(
        active_manager=False,
        subscription_id=sub.prodamus_subscription_id,
        customer_phone=sub.prodamus_customer_phone,
        customer_email=sub.prodamus_customer_email,
        tg_user_id=db_user.telegram_id,
    )
    if not response.get("ok"):
        await callback.message.answer(SUB_CANCEL_FAILED)
        return

    # Локально фиксируем сразу; подтверждающее уведомление Prodamus придёт следом.
    await subscription_repo.mark_cancelled(db_user.id)
    await callback.message.answer(
        SUB_CANCEL_DONE.format(expires=_format_date(sub.expires_at)), parse_mode="HTML"
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
    if message.from_user.id not in ADMIN_USER_IDS:
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
    if message.from_user.id not in ADMIN_USER_IDS:
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
