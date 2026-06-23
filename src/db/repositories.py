"""
Репозитории (DAO) над моделями. Хендлеры работают только через них, не пишут SQL.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import BotUser, CompatibilityResult, Person, SearchHistory, Subscription


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
            .order_by(SearchHistory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


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
