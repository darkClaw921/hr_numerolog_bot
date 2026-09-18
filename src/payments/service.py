"""
Применение уведомления Prodamus к состоянию подписки.

Функция `apply_notification` не знает про HTTP: её вызывает вебхук и тесты.
Подпись к этому моменту уже проверена вызывающим кодом.

Особенности формата Prodamus (сверено с реальным уведомлением):
  * `order_id` — номер заказа Prodamus, а переданный ботом order_id приходит в `order_num`;
  * даты без зоны (`date_next_payment` и т.п.) — московское время.
"""
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import PRODAMUS_GRACE_DAYS, REFERRAL_BONUS_DAYS, SUBSCRIPTION_PERIOD_DAYS
from src.db.models import BotUser, PaymentIntent
from src.db.repositories import (
    PaymentIntentRepo,
    PaymentRepo,
    ReferralRepo,
    SubscriptionRepo,
    UserRepo,
)

logger = logging.getLogger(__name__)

SUCCESS_STATUS = "success"

# Prodamus отдаёт даты без зоны в московском времени (поле `date` приходит с +03:00).
PRODAMUS_TZ = timezone(timedelta(hours=3))

# Что произошло — по этому полю вебхук решает, какое сообщение отправить пользователю.
OUTCOME_ACTIVATED = "activated"
OUTCOME_RENEWED = "renewed"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_FAILED = "failed"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_UNMATCHED = "unmatched"
OUTCOME_IGNORED = "ignored"


@dataclass
class ReferralReward:
    """Бонус пригласившему за первую оплату друга (уведомление и перенос списания — после коммита)."""

    user_id: int
    telegram_id: int | None
    days: int
    expires_at: datetime | None  # None — бессрочный доступ, дни не понадобились
    # Если у пригласившего действует автопродление — дату списания нужно сдвинуть в Prodamus.
    shift_phone: str | None = None
    shift_subscription_id: str | None = None
    shift_to: datetime | None = None
    # Повтор ранее не удавшегося переноса (без уведомления и без нового начисления).
    retry: bool = False


@dataclass
class ApplyResult:
    """Итог обработки одного уведомления."""

    outcome: str
    telegram_id: int | None = None
    expires_at: datetime | None = None
    next_payment_at: datetime | None = None
    order_id: str | None = None
    details: str | None = None
    referral_reward: ReferralReward | None = None
    # Повтор переноса списания для отложенных реферальных дней самого плательщика.
    pending_shift: ReferralReward | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_dict(value) -> dict:
    """Блок subscription приходит вложенным объектом; при его отсутствии — пустой dict."""
    return value if isinstance(value, dict) else {}


def order_ref(data: dict) -> str | None:
    """Идентификатор заказа для логов: наш (order_num), иначе номер Prodamus (order_id)."""
    return data.get("order_num") or data.get("order_id")


def normalize_phone(phone: str | None) -> str | None:
    """'+7 (999) 888-77-66' -> '79998887766'; ведущая 8 приводится к 7."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def parse_prodamus_datetime(value: str | None) -> datetime | None:
    """
    Разбирает даты Prodamus в naive UTC. Дата без зоны ('2026-10-07 12:00:00') —
    московское время; ISO с зоной переводится по своей зоне.
    """
    if not value:
        return None
    text = value.strip()
    for parser in (
        lambda v: datetime.fromisoformat(v),
        lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S"),
        lambda v: datetime.strptime(v, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(text)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=PRODAMUS_TZ)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    logger.warning("Prodamus: не удалось разобрать дату %r", value)
    return None


def build_event_key(data: dict, raw_body: str | None = None) -> str:
    """
    Ключ идемпотентности: Prodamus повторяет доставку при таймауте, и повтор
    не должен продлевать подписку второй раз.
    """
    subscription = _as_dict(data.get("subscription"))
    order_id = data.get("order_id") or ""
    payment_num = subscription.get("payment_num") or ""
    status = data.get("payment_status") or ""
    date = data.get("date") or ""
    key = f"{order_id}:{payment_num}:{status}:{date}"
    if key.strip(":"):
        return key[:191]
    digest = hashlib.sha256((raw_body or repr(sorted(data.items()))).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _is_cancelled(subscription: dict) -> bool:
    """Отмена автопродления: менеджером, пользователем или флагом active."""
    return any(str(subscription.get(field, "1")) == "0" for field in ("active", "active_manager", "active_user"))


async def _find_intent(session: AsyncSession, data: dict) -> PaymentIntent | None:
    """
    Намерение оплаты, выданное ботом. Prodamus возвращает наш order_id в `order_num`;
    `order_id` проверяем на случай, если он придёт как есть.
    """
    intent_repo = PaymentIntentRepo(session)
    for field in ("order_num", "order_id"):
        value = data.get(field)
        if value:
            intent = await intent_repo.get_by_order_id(value)
            if intent is not None:
                return intent
    return None


async def _find_user(session: AsyncSession, data: dict) -> tuple[int | None, int | None]:
    """
    Ищет пользователя по (в порядке надёжности): выданному нами order_id,
    customer_extra, телефону, email. Возвращает (bot_users.id, telegram_id).
    """
    user_repo = UserRepo(session)
    sub_repo = SubscriptionRepo(session)

    intent = await _find_intent(session, data)
    if intent is not None:
        return intent.user_id, await _telegram_id_of(session, intent.user_id)

    extra = data.get("customer_extra") or ""
    match = re.search(r"tg:(\d+)", str(extra))
    if match:
        telegram_id = int(match.group(1))
        user = await user_repo.get_by_telegram_id(telegram_id)
        if user is not None:
            return user.id, user.telegram_id

    phone = normalize_phone(data.get("customer_phone"))
    if phone:
        sub = await sub_repo.find_by_phone(phone)
        if sub is not None:
            return sub.user_id, await _telegram_id_of(session, sub.user_id)

    email = (data.get("customer_email") or "").strip().lower()
    if email:
        sub = await sub_repo.find_by_email(email)
        if sub is not None:
            return sub.user_id, await _telegram_id_of(session, sub.user_id)

    return None, None


async def _telegram_id_of(session: AsyncSession, user_id: int | None) -> int | None:
    if user_id is None:
        return None
    user = await session.get(BotUser, user_id)
    return user.telegram_id if user is not None else None


def _to_amount(value) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def apply_notification(session: AsyncSession, data: dict, raw_body: str | None = None) -> ApplyResult:
    """Применяет проверенное уведомление Prodamus к БД. Не коммитит — это делает вызывающий."""
    subscription = _as_dict(data.get("subscription"))
    ref = order_ref(data)
    status = (data.get("payment_status") or "").strip().lower()
    payment_num = subscription.get("payment_num")
    event_key = build_event_key(data, raw_body)

    payment_repo = PaymentRepo(session)
    if await payment_repo.get_by_event_key(event_key) is not None:
        logger.info("Prodamus: повторная доставка уведомления (order=%s)", ref)
        return ApplyResult(outcome=OUTCOME_DUPLICATE, order_id=ref)

    user_id, telegram_id = await _find_user(session, data)
    kind = "unknown"
    if status == SUCCESS_STATUS:
        kind = "initial" if str(payment_num or "1") == "1" else "renewal"

    payment = await payment_repo.add_event(
        user_id=user_id,
        event_key=event_key,
        order_id=data.get("order_id"),
        order_num=data.get("order_num"),
        amount_rub=_to_amount(data.get("sum")),
        status=status or None,
        payment_type=data.get("payment_type"),
        kind=kind,
        subscription_payment_num=int(payment_num) if str(payment_num or "").isdigit() else None,
        customer_phone=normalize_phone(data.get("customer_phone")),
        customer_email=(data.get("customer_email") or None),
        raw_payload=data,
    )
    if payment is None:
        # Гонка двух одновременных доставок — вторая проиграла уникальному индексу.
        logger.info("Prodamus: дубль по event_key (order=%s)", ref)
        return ApplyResult(outcome=OUTCOME_DUPLICATE, order_id=ref)

    if user_id is None:
        logger.error("Prodamus: не удалось сопоставить пользователя (order=%s)", ref)
        return ApplyResult(outcome=OUTCOME_UNMATCHED, order_id=ref)

    sub_repo = SubscriptionRepo(session)

    if status == SUCCESS_STATUS:
        next_payment_at = parse_prodamus_datetime(subscription.get("date_next_payment"))
        current = await sub_repo.get(user_id)
        if next_payment_at is not None:
            # Запас, чтобы доступ не пропал между попыткой списания и её повтором.
            expires_at = next_payment_at + timedelta(days=PRODAMUS_GRACE_DAYS)
        else:
            # Продление от конца оплаченного периода, а не от «сейчас»: досрочное
            # списание не должно съедать остаток.
            base = current.expires_at if current is not None and current.expires_at else None
            if base is not None and base.tzinfo is not None:
                base = base.replace(tzinfo=None)
            start = max(base, _utcnow()) if base is not None else _utcnow()
            expires_at = start + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
        if current is not None and current.expires_at is not None:
            # Не укорачиваем уже выданный доступ (например, реферальные бонусные дни).
            expires_at = max(expires_at, current.expires_at.replace(tzinfo=None))

        await sub_repo.apply_prodamus_payment(
            user_id,
            expires_at=expires_at,
            next_payment_at=next_payment_at,
            prodamus_subscription_id=str(subscription.get("id")) if subscription.get("id") else None,
            customer_phone=normalize_phone(data.get("customer_phone")),
            customer_email=(data.get("customer_email") or None),
        )
        intent = await _find_intent(session, data)
        if intent is not None and intent.paid_at is None:
            await PaymentIntentRepo(session).mark_paid(intent)

        if _is_cancelled(subscription):
            # Оплату засчитываем, но автопродление на стороне Prodamus уже отключено.
            await sub_repo.mark_cancelled(user_id)

        # Бонус — только за реальную оплату: при пробном периоде первое уведомление может
        # прийти с нулевой суммой.
        amount = _to_amount(data.get("sum")) or 0
        reward = await _reward_referrer(session, user_id) if kind == "initial" and amount > 0 else None
        pending_shift = await _pending_shift(session, user_id)

        return ApplyResult(
            outcome=OUTCOME_ACTIVATED if kind == "initial" else OUTCOME_RENEWED,
            telegram_id=telegram_id,
            expires_at=expires_at,
            next_payment_at=next_payment_at,
            order_id=ref,
            referral_reward=reward,
            pending_shift=pending_shift,
        )

    if subscription and _is_cancelled(subscription):
        sub = await sub_repo.mark_cancelled(user_id)
        return ApplyResult(
            outcome=OUTCOME_CANCELLED,
            telegram_id=telegram_id,
            expires_at=sub.expires_at if sub is not None else None,
            order_id=ref,
        )

    if status and status != SUCCESS_STATUS:
        # Срок не трогаем: доступ снимется сам по expires_at, отдельный крон не нужен.
        attempt = str(subscription.get("current_attempt") or "")
        max_attempts = str(subscription.get("max_attempts") or "")
        exhausted = attempt.isdigit() and max_attempts.isdigit() and int(attempt) >= int(max_attempts)
        return ApplyResult(
            outcome=OUTCOME_FAILED,
            telegram_id=telegram_id,
            order_id=ref,
            details=data.get("payment_status_description"),
            next_payment_at=parse_prodamus_datetime(subscription.get("date_next_payment")) if not exhausted else None,
        )

    return ApplyResult(outcome=OUTCOME_IGNORED, telegram_id=telegram_id, order_id=ref)


async def _reward_referrer(session: AsyncSession, user_id: int) -> ReferralReward | None:
    """
    Начисляет пригласившему бонусные дни за первую оплату приглашённого (один раз).

    Доступ продлевается сразу в БД. Если у пригласившего идёт автопродление, дату
    списания в Prodamus нужно сдвинуть на те же дни — это сетевой вызов, его делает
    вебхук после коммита (см. ReferralReward.shift_*).
    """
    referral_repo = ReferralRepo(session)
    referral = await referral_repo.get_by_referred(user_id)
    if referral is None or referral.rewarded_at is not None or REFERRAL_BONUS_DAYS <= 0:
        return None

    sub_repo = SubscriptionRepo(session)
    referrer_id = referral.referrer_user_id
    before = await sub_repo.get(referrer_id)
    lifetime = before is not None and before.expires_at is None and await sub_repo.is_active(referrer_id)
    sub = await sub_repo.add_bonus_days(referrer_id, REFERRAL_BONUS_DAYS)
    await referral_repo.mark_rewarded(referral, REFERRAL_BONUS_DAYS if not lifetime else 0)

    reward = ReferralReward(
        user_id=referrer_id,
        telegram_id=await _telegram_id_of(session, referrer_id),
        days=REFERRAL_BONUS_DAYS,
        expires_at=None if lifetime else sub.expires_at,
    )
    if not lifetime and _has_upcoming_charge(sub):
        reward.shift_phone = sub.prodamus_customer_phone
        reward.shift_subscription_id = sub.prodamus_subscription_id
        reward.shift_to = sub.next_payment_at.replace(tzinfo=None) + timedelta(days=REFERRAL_BONUS_DAYS)
    logger.info("Реферальный бонус: user=%s +%s дн. (за user=%s)", referrer_id, REFERRAL_BONUS_DAYS, user_id)
    return reward


def _has_upcoming_charge(sub) -> bool:
    """
    Идёт ли автопродление с будущей датой списания. Дату в прошлом (подписка
    «зависла» после неудачных списаний) Prodamus не даст сдвинуть — не пытаемся.
    """
    return bool(
        sub is not None
        and sub.prodamus_active
        and sub.prodamus_customer_phone
        and sub.next_payment_at is not None
        and sub.next_payment_at.replace(tzinfo=None) > _utcnow()
    )


async def _pending_shift(session: AsyncSession, user_id: int) -> ReferralReward | None:
    """Если у плательщика есть отложенные реферальные дни — повторяем перенос списания."""
    sub = await SubscriptionRepo(session).get(user_id)
    days = sub.referral_bonus_pending_days if sub is not None else None
    if not days or not _has_upcoming_charge(sub):
        return None
    return ReferralReward(
        user_id=user_id,
        telegram_id=None,
        days=days,
        expires_at=sub.expires_at,
        shift_phone=sub.prodamus_customer_phone,
        shift_subscription_id=sub.prodamus_subscription_id,
        shift_to=sub.next_payment_at.replace(tzinfo=None) + timedelta(days=days),
        retry=True,
    )
