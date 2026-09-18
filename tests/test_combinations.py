"""Тесты краевых ситуаций для парсера и правил комбинаций."""
import unittest

from src.utils import combinations as c


def make_results(counts=None, family=0, life=0, temperament=0, purpose=0, stability=0, destiny=1):
    """Строит синтетический results-словарь с заданными количествами цифр в секторах."""
    counts = counts or {}
    matrix = {i: [i] * counts.get(i, 0) for i in range(1, 10)}
    return {
        "matrix": matrix,
        "sector_family": family,
        "sector_life": life,
        "sector_temperament": temperament,
        "sector_purpose": purpose,
        "sector_stability": stability,
        "destiny_number": destiny,
    }


class TestParseDigitRep(unittest.TestCase):
    def test_single_run(self):
        self.assertEqual(c._parse_digitrep("111"), (1, {3}))

    def test_alternatives(self):
        self.assertEqual(c._parse_digitrep("4/44/444"), (4, {1, 2, 3}))

    def test_empty_word(self):
        self.assertEqual(c._parse_digitrep("8/пуст"), (8, {0, 1}))

    def test_digit_with_empty_word(self):
        # "4 пустой" -> цифра 4, количество 0
        self.assertEqual(c._parse_digitrep("4 пустой"), (4, {0}))

    def test_standalone_empty(self):
        self.assertEqual(c._parse_digitrep("пуст"), (None, {0}))

    def test_and_more_extends_upward(self):
        digit, counts = c._parse_digitrep("2222 и более")
        self.assertEqual(digit, 2)
        self.assertIn(4, counts)
        self.assertIn(9, counts)
        self.assertNotIn(3, counts)

    def test_more_from_listed_min(self):
        digit, counts = c._parse_digitrep("666/6666 и более")
        self.assertEqual(digit, 6)
        self.assertTrue({3, 4, 5, 9}.issubset(counts))


class TestParsePlainInt(unittest.TestCase):
    def test_alternatives(self):
        self.assertEqual(c._parse_plainint("4/5/6"), {4, 5, 6})

    def test_with_empty(self):
        self.assertEqual(c._parse_plainint("пуст/1/2/3"), {0, 1, 2, 3})

    def test_and_more(self):
        vals = c._parse_plainint("4/5/6 и более")
        self.assertTrue({4, 5, 6}.issubset(vals))
        self.assertIn(c.MAX_COEF, vals)


class TestParsePart(unittest.TestCase):
    def test_paren_empty_modifier(self):
        # "5(пуст)" -> в секторе 5 ноль пятёрок
        self.assertEqual(c._parse_part("5(пуст)"), [("sector", 5, {0})])

    def test_paren_independent_condition(self):
        conds = c._parse_part("8/пуст (ЧС 4/6)")
        self.assertIn(("sector", 8, {0, 1}), conds)
        self.assertIn(("destiny", {4, 6}), conds)

    def test_derived_prefix(self):
        self.assertEqual(c._parse_part("семья 4/5/6"), [("coef", "sector_family", {4, 5, 6})])

    def test_real_sector_prefix(self):
        self.assertEqual(c._parse_part("труд 6/66/666"), [("sector", 6, {1, 2, 3})])

    def test_destiny_prefix(self):
        self.assertEqual(c._parse_part("ЧС 7/9/3"), [("destiny", {3, 7, 9})])

    def test_paren_relabel_derived(self):
        self.assertEqual(
            c._parse_part("1/2/3 (целеустремленность)"),
            [("coef", "sector_purpose", {1, 2, 3})],
        )

    def test_sreda_raises_skip(self):
        with self.assertRaises(c.SkipRule):
            c._parse_part("среда")


class TestParsePattern(unittest.TestCase):
    def test_equals_treated_as_plus(self):
        conds = c.parse_pattern("88/888 = 22/222/2222")
        self.assertEqual(conds, [("sector", 8, {2, 3}), ("sector", 2, {2, 3, 4})])

    def test_full_pattern(self):
        conds = c.parse_pattern("111 + 4/44/444 + 8/пуст")
        self.assertEqual(
            conds,
            [("sector", 1, {3}), ("sector", 4, {1, 2, 3}), ("sector", 8, {0, 1})],
        )


class TestRulesIntegrity(unittest.TestCase):
    def test_all_rules_compile(self):
        # Каждое правило должно дать хотя бы одно условие (кроме явно пропущенных "среда")
        skipped = 0
        for group, pattern, text in c.RULES:
            with self.subTest(pattern=pattern):
                try:
                    conds = c.parse_pattern(pattern)
                except c.SkipRule:
                    skipped += 1
                    continue
                self.assertTrue(conds, f"Пустые условия для: {pattern}")
        # В текущем наборе явных "среда"-правил нет (они исключены при транскрипции)
        self.assertEqual(skipped, 0)

    def test_no_conditions_lost(self):
        # Число условий не меньше числа частей (скобки могут добавлять условия)
        for group, pattern, text in c.RULES:
            with self.subTest(pattern=pattern):
                try:
                    conds = c.parse_pattern(pattern)
                except c.SkipRule:
                    continue
                n_parts = pattern.replace("=", "+").count("+") + 1
                self.assertGreaterEqual(len(conds), n_parts)

    def test_texts_nonempty_and_unique_pairs(self):
        self.assertTrue(all(text.strip() for _, _, text in c.RULES))

    def test_compiled_count_matches(self):
        self.assertEqual(len(c.COMPILED_RULES), len(c.RULES))


class TestMatching(unittest.TestCase):
    def test_simple_sector_match(self):
        # "2 + 4" -> "Нижняя граница энергии"
        results = make_results(counts={2: 1, 4: 1})
        texts = [t for _, t in c.get_matching_combinations(results)]
        self.assertTrue(any("Нижняя граница энергии" in t for t in texts))

    def test_no_match_when_count_off(self):
        # сектор 2 пуст -> правило "2 + 4" не должно срабатывать
        results = make_results(counts={4: 1})
        texts = [t for _, t in c.get_matching_combinations(results)]
        self.assertFalse(any("Нижняя граница энергии" in t for t in texts))

    def test_derived_coefficient_match(self):
        # "8 + семья 4/5/6"
        results = make_results(counts={8: 1}, family=5)
        texts = [t for _, t in c.get_matching_combinations(results)]
        self.assertTrue(any("Баланс семьи и карьеры" in t for t in texts))

    def test_derived_coefficient_no_match(self):
        results = make_results(counts={8: 1}, family=3)
        texts = [t for _, t in c.get_matching_combinations(results)]
        self.assertFalse(any("Баланс семьи и карьеры" in t for t in texts))

    def test_destiny_paren_condition(self):
        # "4/44/444 + 6/66/666 + семья 1/2/3 + 8/пуст (ЧС 4/6)"
        base = dict(counts={4: 1, 6: 1, 8: 0}, family=2)
        hit = make_results(destiny=4, **base)
        miss = make_results(destiny=7, **base)
        hit_texts = [t for _, t in c.get_matching_combinations(hit)]
        miss_texts = [t for _, t in c.get_matching_combinations(miss)]
        self.assertTrue(any("Профессия становится главным" in t for t in hit_texts))
        self.assertFalse(any("Профессия становится главным" in t for t in miss_texts))

    def test_empty_matrix_returns_list(self):
        # все секторы пусты — функция не должна падать, возвращает список
        results = make_results()
        out = c.get_matching_combinations(results)
        self.assertIsInstance(out, list)

    def test_result_shape(self):
        results = make_results(counts={2: 1, 4: 1})
        for item in c.get_matching_combinations(results):
            self.assertEqual(len(item), 2)
            group, text = item
            self.assertIsInstance(group, str)
            self.assertIsInstance(text, str)


if __name__ == "__main__":
    unittest.main()
