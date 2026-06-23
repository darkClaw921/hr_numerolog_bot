"""Тесты переименования сектора 6 и меток комбинаций."""
import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.texts import SECTOR_NAMES  # noqa: E402
from src.utils.combinations import RULES  # noqa: E402


class TestSectorRename(unittest.TestCase):
    def test_sector6_renamed(self):
        self.assertEqual(SECTOR_NAMES[6], "ДЕНЬГИ/ТРУД")

    def test_combination_group_renamed(self):
        groups = {group for group, _pattern, _text in RULES}
        self.assertNotIn("ТРУД (6)", groups)
        self.assertIn("ДЕНЬГИ/ТРУД (6)", groups)
