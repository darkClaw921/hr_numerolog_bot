"""Тесты форматирования результатов и сборки полного отчёта."""
import os
import re
import unittest

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.formatting import (  # noqa: E402
    _html_to_markdown,
    build_full_report,
    build_full_report_markdown,
    format_results_basic,
    person_label,
)
from src.utils.combinations import get_matching_combinations  # noqa: E402
from src.utils.numerology import calculate_all  # noqa: E402

DATE = "18.08.1984"


class TestBasicLayout(unittest.TestCase):
    def setUp(self):
        self.results = calculate_all(DATE)
        self.basic = format_results_basic(self.results)

    def test_additional_numbers_below_destiny(self):
        # По ТЗ блок «Дополнительные числа» перемещён вниз.
        self.assertGreater(
            self.basic.index("Дополнительные числа"),
            self.basic.index("Число Судьбы"),
        )

    def test_sector6_label(self):
        self.assertIn("ДЕНЬГИ/ТРУД", self.basic)


class TestFullReport(unittest.TestCase):
    def setUp(self):
        self.results = calculate_all(DATE)
        self.matches = get_matching_combinations(self.results)
        self.html = build_full_report(self.results, "Тест", self.matches)
        self.md = build_full_report_markdown(self.results, "Тест", self.matches)

    def test_contains_all_nine_sectors(self):
        self.assertEqual(self.html.count("Сектор "), 18)  # 9 в матрице + 9 в блоке секторов

    def test_contains_all_qualities(self):
        for q in ["БЫТ", "СЕМЬЯ", "СТАБИЛЬНОСТЬ", "ЦЕЛЕУСТРЕМЛЕННОСТЬ", "ТРАНСФОРМАЦИЯ", "ЧИСЛО СУДЬБЫ"]:
            self.assertIn(q, self.html)

    def test_markdown_has_no_html_tags(self):
        self.assertIsNone(re.search(r"</?[a-zA-Z][^>]*>", self.md))

    def test_markdown_has_bold(self):
        self.assertIn("**", self.md)


class TestHtmlToMarkdown(unittest.TestCase):
    def test_bold_italic(self):
        self.assertEqual(_html_to_markdown("<b>X</b>"), "**X**")
        self.assertEqual(_html_to_markdown("<i>Y</i>"), "_Y_")

    def test_strips_other_tags(self):
        self.assertNotIn("<", _html_to_markdown("<span>z</span>"))


class TestPersonLabel(unittest.TestCase):
    def test_name_priority(self):
        self.assertEqual(person_label("Имя", "ФИО"), "Имя")

    def test_full_name_fallback(self):
        self.assertEqual(person_label(None, "ФИО"), "ФИО")

    def test_default(self):
        self.assertEqual(person_label(None, None), "Без имени")
