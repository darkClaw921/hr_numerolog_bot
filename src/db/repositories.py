"""
Репозитории (DAO) над моделями. Хендлеры работают только через них, не пишут SQL.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    BotUser,
    CompatibilityResult,
    Payment,
    PaymentIntent,
    Person,
    Referral,
    SearchHistory,
    Subscription,
)


def _utcnow() -> datetime:
    """Текущее время UTC без tzinfo (для единообразного сравнения с expires_at)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> BotUser | None:
        result = await self.session.execute(
            select(BotUser).where(BotUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
    ) -> BotUser:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = BotUser(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            # Обновляем профиль, если изменился username/имя.
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            if language_code:
                user.language_code = language_code
        return user


class PersonRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        owner_user_id: int,
        birth_date: date,
        display_name: str | None = None,
        full_name: str | None = None,
        calc_snapshot: dict | None = None,
        calc_version: int = 1,
        destiny_number: int | None = None,
    ) -> Person:
        person = Person(
            owner_user_id=owner_user_id,
            birth_date=birth_date,
            display_name=display_name,
            full_name=full_name,
            calc_snapshot=calc_snapshot,
            calc_version=calc_version,
            destiny_number=destiny_number,
        )
        self.session.add(person)
        await self.session.flush()
        return person

    async def list(self, owner_user_id: int) -> list[Person]:
        result = await self.session.execute(
            select(Person)
            .where(Person.owner_user_id == owner_user_id)
            .order_by(Person.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_by_birth_date(self, owner_user_id: int, birth_date: date) -> Person | None:
        """Последний сохранённый человек с этой датой — чтобы не предлагать сохранить повторно."""
        result = await self.session.execute(
            select(Person)
            .where(Person.owner_user_id == owner_user_id, Person.birth_date == birth_date)
            .order_by(Person.created_at.desc(), Person.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get(self, person_id: int, owner_user_id: int) -> Person | None:
        result = await self.session.execute(
            select(Person).where(
                Person.id == person_id,
                Person.owner_user_id == owner_user_id,
            )
        )
        return result.scalar_one_or_none()


class SearchHistoryRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        user_id: int,
        birth_date: date,
        person_id: int | None = None,
        raw_query: str | None = None,
    ) -> SearchHistory:
        item = SearchHistory(
            user_id=user_id,
            birth_date=birth_date,
            person_id=person_id,
            raw_query=raw_query,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list(self, user_id: int, limit: int = 20) -> list[SearchHistory]:
        result = await self.session.execute(
            select(SearchHistory)
            .where(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.created_at.desc(), SearchHistory.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_unique(self, user_id: int, limit: int = 15) -> "list[tuple[SearchHistory, Person | None]]":
        """
        Кого искал — без повторов: последний поиск по каждому человеку/дате.
        Возвращает пары (запись истории, сохранённый человек или None).
        """
        result = await self.session.execute(
            select(SearchHistory, Person)
            .outerjoin(Person, Person.id == SearchHistory.person_id)
            .where(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.created_at.desc(), SearchHistory.id.desc())
            .limit(limit * 10)
        )
        seen: set = set()
        items = []
        for item, person in result.all():
            key = ("p", person.id) if person is not None else ("d", item.birth_date)
            if key in seen:
                continue
            seen.add(key)
            items.append((item, person))
            if len(items) >= limit:
                break
        return items


class SubscriptionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def is_active(self, user_id: int) -> bool:
        sub = await self.get(user_id)
        if sub is None or not sub.is_premium:
            return False
        if sub.expires_at is None:
            return True
        expires = sub.expires_at
        if expires.tzinfo is not None:
            expires = expires.replace(tzinfo=None)
        return expires > _utcnow()

    async def set_premium(
        self,
        user_id: int,
        is_premium: bool = True,
        days: int | None = None,
        plan: str = "premium_monthly",
    ) -> Subscription:
        """Создаёт/обновляет подписку. days=None → бессрочно (expires_at=NULL)."""
        sub = await self.get(user_id)
        now = _utcnow()
        expires_at = now + timedelta(days=days) if days else None
        if sub is None:
            sub = Subscription(
                user_id=user_id,
                is_premium=is_premium,
                plan=plan if is_premium else "free",
                started_at=now if is_premium else None,
                expires_at=expires_at,
            )
            self.session.add(sub)
            await self.session.flush()
        else:
            sub.is_premium = is_premium
            sub.plan = plan if is_premium else "free"
            sub.started_at = now if is_premium else sub.started_at
            sub.expires_at = expires_at
        return sub

    async def apply_prodamus_payment(
        self,
        user_id: int,
        *,
        expires_at: datetime,
        next_payment_at: datetime | None = None,
        prodamus_subscription_id: str | None = None,
        customer_phone: str | None = None,
        customer_email: str | None = None,
        plan: str = "premium_monthly",
    ) -> Subscription:
        """Включает/продлевает премиум по успешному платежу Prodamus."""
        sub = await self.get(user_id)
        now = _utcnow()
        if sub is None:
            sub = Subscription(user_id=user_id, is_premium=True, plan=plan, started_at=now)
            self.session.add(sub)
        sub.is_premium = True
        sub.plan = plan
        sub.started_at = sub.started_at or now
        sub.expires_at = expires_at
        sub.provider = "prodamus"
        sub.prodamus_active = True
        # Успешное списание отменяет прошлую отмену автопродления.
        sub.cancelled_at = None
        sub.last_payment_at = now
        sub.next_payment_at = next_payment_at
        if prodamus_subscription_id:
            sub.prodamus_subscription_id = prodamus_subscription_id
        if customer_phone:
            sub.prodamus_customer_phone = customer_phone
        if customer_email:
            sub.prodamus_customer_email = customer_email
        await self.session.flush()
        return sub

    async def mark_cancelled(self, user_id: int) -> Subscription | None:
        """
        Отключает автопродление. is_premium и expires_at НЕ трогаем: оплаченный
        период дорабатывает до конца, дальше доступ снимет сам is_active().
        """
        sub = await self.get(user_id)
        if sub is None:
            return None
        sub.prodamus_active = False
        sub.cancelled_at = _utcnow()
        await self.session.flush()
        return sub

    async def add_bonus_days(self, user_id: int, days: int) -> Subscription:
        """
        Продлевает доступ на `days` дней (реферальный бонус).

        Активная подписка продлевается от конца оплаченного периода, неактивная —
        включается с «сейчас». Бессрочный премиум (expires_at IS NULL) не меняется.
        """
        sub = await self.get(user_id)
        now = _utcnow()
        if sub is None:
            sub = Subscription(user_id=user_id, is_premium=True, plan="referral_bonus", started_at=now,
                               expires_at=now + timedelta(days=days))
            self.session.add(sub)
            await self.session.flush()
            return sub
        active = await self.is_active(user_id)
        if active and sub.expires_at is None:
            return sub
        base = sub.expires_at.replace(tzinfo=None) if active else now
        if not active:
            sub.is_premium = True
            sub.started_at = now
            if not sub.provider:
                sub.plan = "referral_bonus"
        sub.expires_at = base + timedelta(days=days)
        await self.session.flush()
        return sub

    async def shift_next_payment(self, user_id: int, next_payment_at: datetime, grace_days: int = 0) -> None:
        """
        Фиксирует перенесённую в Prodamus дату следующего списания: доступ тянется до
        новой даты (+ запас), отложенные бонусные дни считаются выданными.
        """
        sub = await self.get(user_id)
        if sub is None:
            return
        sub.next_payment_at = next_payment_at
        sub.referral_bonus_pending_days = None
        until = next_payment_at + timedelta(days=grace_days)
        current = sub.expires_at.replace(tzinfo=None) if sub.expires_at is not None else None
        if current is not None and current < until:
            sub.expires_at = until
        await self.session.flush()

    async def add_pending_bonus(self, user_id: int, days: int) -> None:
        """Бонусные дни, которые не удалось отразить переносом списания в Prodamus (повторим позже)."""
        sub = await self.get(user_id)
        if sub is not None:
            sub.referral_bonus_pending_days = (sub.referral_bonus_pending_days or 0) + days
            await self.session.flush()

    async def find_by_phone(self, phone: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.prodamus_customer_phone == phone)
        )
        return result.scalars().first()

    async def find_by_email(self, email: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.prodamus_customer_email == email)
        )
        return result.scalars().first()


class PaymentIntentRepo:
    """Намерения оплаты: связывают выданный ботом order_id с пользователем."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, order_id: str, amount_rub: float | None = None) -> PaymentIntent:
        intent = PaymentIntent(user_id=user_id, order_id=order_id, amount_rub=amount_rub)
        self.session.add(intent)
        await self.session.flush()
        return intent

    async def get_by_order_id(self, order_id: str) -> PaymentIntent | None:
        result = await self.session.execute(
            select(PaymentIntent).where(PaymentIntent.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def mark_paid(self, intent: PaymentIntent) -> None:
        intent.paid_at = _utcnow()
        await self.session.flush()


class PaymentRepo:
    """Журнал платёжных событий; event_key обеспечивает идемпотентность вебхука."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_event(self, **fields) -> Payment | None:
        """
        Пишет событие. Возвращает None, если событие с таким event_key уже было
        (повторная доставка уведомления) — вызывающий код тогда ничего не меняет.
        """
        payment = Payment(**fields)
        self.session.add(payment)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return None
        return payment

    async def get_by_event_key(self, event_key: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.event_key == event_key)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int, limit: int = 10) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class ReferralRepo:
    """Реферальные приглашения и начисление бонусов пригласившему."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_referred(self, referred_user_id: int) -> Referral | None:
        result = await self.session.execute(
            select(Referral).where(Referral.referred_user_id == referred_user_id)
        )
        return result.scalar_one_or_none()

    async def attach(self, referrer_user_id: int, referred_user_id: int) -> Referral | None:
        """Привязывает приглашённого к пригласившему. None — уже привязан или сам себя."""
        if referrer_user_id == referred_user_id:
            return None
        if await self.get_by_referred(referred_user_id) is not None:
            return None
        referral = Referral(referrer_user_id=referrer_user_id, referred_user_id=referred_user_id)
        try:
            # SAVEPOINT: при конфликте откатываем только вставку, а не всю сессию апдейта
            # (полный rollback «протух» бы db_user и прочие объекты хендлера).
            async with self.session.begin_nested():
                self.session.add(referral)
        except IntegrityError:
            # Гонка двух /start с разными ссылками: побеждает первая.
            return None
        return referral

    async def mark_rewarded(self, referral: Referral, days: int) -> None:
        referral.rewarded_at = _utcnow()
        referral.bonus_days = days
        await self.session.flush()

    async def stats(self, referrer_user_id: int) -> dict:
        """Сколько приглашено, сколько оплатило и сколько бонусных дней получено."""
        result = await self.session.execute(
            select(
                func.count(Referral.id),
                func.count(Referral.rewarded_at),
                func.coalesce(func.sum(Referral.bonus_days), 0),
            ).where(Referral.referrer_user_id == referrer_user_id)
        )
        invited, paid, bonus_days = result.one()
        return {"invited": invited, "paid": paid, "bonus_days": int(bonus_days or 0)}


class CompatibilityRepo:
    """Задел для бота совместимости; текущий бот не использует."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        person_a_id: int,
        person_b_id: int,
        score: float | None = None,
        details: dict | None = None,
        requested_by: int | None = None,
        calc_version: int = 1,
    ) -> CompatibilityResult:
        result = CompatibilityResult(
            person_a_id=person_a_id,
            person_b_id=person_b_id,
            score=score,
            details=details,
            requested_by=requested_by,
            calc_version=calc_version,
        )
        self.session.add(result)
        await self.session.flush()
        return result
