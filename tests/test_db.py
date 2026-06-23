"""Тесты слоя БД (репозитории) на временной SQLite-базе."""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.db.base import Base  # noqa: E402
from src.db.repositories import (  # noqa: E402
    PersonRepo,
    SearchHistoryRepo,
    SubscriptionRepo,
    UserRepo,
)


class TestRepositories(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self._tmp.name}")
        async with self.engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.commit()
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        os.unlink(self._tmp.name)

    async def test_user_get_or_create_idempotent(self):
        async with self.factory() as s:
            u1 = await UserRepo(s).get_or_create(telegram_id=10, username="a")
            await s.commit()
            u2 = await UserRepo(s).get_or_create(telegram_id=10, username="b")
            await s.commit()
            self.assertEqual(u1.id, u2.id)
            self.assertEqual(u2.username, "b")

    async def test_person_roundtrip(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=11)
            await PersonRepo(s).add(
                owner_user_id=u.id,
                birth_date=date(1984, 8, 18),
                display_name="X",
                calc_snapshot={"matrix": {"1": [1]}},
                destiny_number=3,
            )
            await s.commit()
            people = await PersonRepo(s).list(u.id)
            self.assertEqual(len(people), 1)
            self.assertEqual(people[0].destiny_number, 3)
            self.assertEqual(people[0].calc_snapshot["matrix"]["1"], [1])

    async def test_history(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=12)
            await SearchHistoryRepo(s).add(user_id=u.id, birth_date=date(1990, 1, 1), raw_query="01.01.1990")
            await s.commit()
            items = await SearchHistoryRepo(s).list(u.id)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].raw_query, "01.01.1990")

    async def test_subscription_lifecycle(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=13)
            repo = SubscriptionRepo(s)
            self.assertFalse(await repo.is_active(u.id))
            await repo.set_premium(u.id, days=30)
            await s.commit()
            self.assertTrue(await repo.is_active(u.id))

    async def test_subscription_expired(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=14)
            repo = SubscriptionRepo(s)
            await repo.set_premium(u.id, days=-1)  # истекла вчера
            await s.commit()
            self.assertFalse(await repo.is_active(u.id))

    async def test_subscription_unlimited(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=15)
            repo = SubscriptionRepo(s)
            await repo.set_premium(u.id, days=None)  # бессрочно
            await s.commit()
            self.assertTrue(await repo.is_active(u.id))
