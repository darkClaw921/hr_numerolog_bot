"""Тесты gating платных функций."""
import os
import types
import unittest

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src import access  # noqa: E402


def _user(telegram_id: int, internal_id: int = 1):
    return types.SimpleNamespace(telegram_id=telegram_id, id=internal_id)


class TestFeatureMapping(unittest.TestCase):
    def test_paid_features(self):
        for f in ["report", "combinations", "life", "temperament", "family", "stability", "transformation"]:
            with self.subTest(f=f):
                self.assertTrue(access.is_premium_feature(f))

    def test_free_features(self):
        # Цель, Число Судьбы и любые секторы 1-9 бесплатны.
        for f in ["purpose", "destiny_number", "character", "energy", "luck", "memory"]:
            with self.subTest(f=f):
                self.assertFalse(access.is_premium_feature(f))


class TestIsPremium(unittest.IsolatedAsyncioTestCase):
    async def test_premium_user_ids_fallback(self):
        access.PREMIUM_USER_IDS.add(424242)
        try:
            self.assertTrue(await access.is_premium(_user(424242)))
            self.assertFalse(await access.is_premium(_user(111)))
        finally:
            access.PREMIUM_USER_IDS.discard(424242)

    async def test_no_repo_no_premium(self):
        self.assertFalse(await access.is_premium(_user(987654)))
