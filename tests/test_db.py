"""Тесты слоя БД (репозитории) на временной SQLite-базе."""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.db.base import Base  # noqa: E402
from src.db.migrations import ensure_schema  # noqa: E402
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


class TestSchemaMigration(unittest.IsolatedAsyncioTestCase):
    """Мини-миграции: alembic нет, колонки в существующие таблицы добавляем сами."""

    async def asyncSetUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self._tmp.name}")

    async def asyncTearDown(self):
        await self.engine.dispose()
        os.unlink(self._tmp.name)

    async def _columns(self, conn, table: str) -> set[str]:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        return {row[1] for row in result.fetchall()}

    async def test_adds_missing_columns_to_legacy_table(self):
        legacy_ddl = (
            "CREATE TABLE subscriptions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id BIGINT NOT NULL UNIQUE, "
            "is_premium BOOLEAN NOT NULL, plan VARCHAR(32) NOT NULL, price_rub INTEGER NOT NULL, "
            "started_at DATETIME, expires_at DATETIME, created_at DATETIME, updated_at DATETIME)"
        )
        async with self.engine.connect() as conn:
            await conn.exec_driver_sql(legacy_ddl)
            await conn.exec_driver_sql(
                "INSERT INTO subscriptions (user_id, is_premium, plan, price_rub) VALUES (1, 1, 'premium_monthly', 299)"
            )
            await conn.commit()

            await ensure_schema(conn)
            await conn.commit()

            columns = await self._columns(conn, "subscriptions")
            self.assertIn("prodamus_subscription_id", columns)
            self.assertIn("cancelled_at", columns)
            # Существующие данные не пострадали.
            result = await conn.exec_driver_sql("SELECT user_id, is_premium FROM subscriptions")
            self.assertEqual(result.fetchall(), [(1, 1)])

    async def test_idempotent(self):
        async with self.engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.commit()
            await ensure_schema(conn)
            await ensure_schema(conn)
            await conn.commit()
            self.assertIn("provider", await self._columns(conn, "subscriptions"))

    async def test_skips_absent_table(self):
        """Пустая БД: таблиц ещё нет — миграция не должна падать."""
        async with self.engine.connect() as conn:
            await ensure_schema(conn)
            await conn.commit()
