"""Интеграционные тесты потока расчёта и gating через временную БД."""
import os
import tempfile
import types
import unittest
from datetime import date

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.access import require_premium  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.repositories import (  # noqa: E402
    SearchHistoryRepo,
    SubscriptionRepo,
    UserRepo,
)
from src.handlers.calculation import process_date  # noqa: E402


class StubMessage:
    """Минимальная замена aiogram Message для проверки логики хендлеров."""

    def __init__(self, text: str, user_id: int):
        self.text = text
        self.from_user = types.SimpleNamespace(id=user_id)
        self.sent = []  # список (text, reply_markup)

    async def answer(self, text, parse_mode=None, reply_markup=None):
        self.sent.append((text, reply_markup))
        return self


class TestProcessDate(unittest.IsolatedAsyncioTestCase):
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

    async def test_process_date_renders_and_records_history(self):
        async with self.factory() as s:
            db_user = await UserRepo(s).get_or_create(telegram_id=777, first_name="T")
            await s.commit()
            msg = StubMessage("18.08.1984", user_id=777)
            await process_date(msg, SubscriptionRepo(s), SearchHistoryRepo(s), db_user)
            await s.commit()

            # Отправлен экран результатов с клавиатурой.
            self.assertEqual(len(msg.sent), 1)
            text, keyboard = msg.sent[0]
            self.assertIn("Результаты расчетов", text)
            self.assertIn("ДЕНЬГИ/ТРУД", text)
            self.assertIsNotNone(keyboard)

            # История поиска записана.
            history = await SearchHistoryRepo(s).list(db_user.id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].raw_query, "18.08.1984")

    async def test_keyboard_shows_locks_for_non_premium(self):
        async with self.factory() as s:
            db_user = await UserRepo(s).get_or_create(telegram_id=778)
            await s.commit()
            msg = StubMessage("18.08.1984", user_id=778)
            await process_date(msg, SubscriptionRepo(s), SearchHistoryRepo(s), db_user)
            _, keyboard = msg.sent[0]
            all_texts = " ".join(btn.text for row in keyboard.inline_keyboard for btn in row)
            self.assertIn("🔒", all_texts)  # платные кнопки помечены замком

    async def test_keyboard_no_locks_for_premium(self):
        async with self.factory() as s:
            db_user = await UserRepo(s).get_or_create(telegram_id=779)
            await SubscriptionRepo(s).set_premium(db_user.id, days=30)
            await s.commit()
            msg = StubMessage("18.08.1984", user_id=779)
            await process_date(msg, SubscriptionRepo(s), SearchHistoryRepo(s), db_user)
            _, keyboard = msg.sent[0]
            all_texts = " ".join(btn.text for row in keyboard.inline_keyboard for btn in row)
            self.assertNotIn("🔒", all_texts)


class TestRequirePremium(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_non_premium_message(self):
        db_user = types.SimpleNamespace(telegram_id=1, id=1)
        event = StubMessage("x", user_id=1)
        allowed = await require_premium(event, "report", db_user, None)
        self.assertFalse(allowed)
        self.assertEqual(len(event.sent), 1)  # отправлен paywall

    async def test_free_feature_always_allowed(self):
        db_user = types.SimpleNamespace(telegram_id=1, id=1)
        event = StubMessage("x", user_id=1)
        allowed = await require_premium(event, "purpose", db_user, None)
        self.assertTrue(allowed)
        self.assertEqual(len(event.sent), 0)
