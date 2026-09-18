"""Тесты краевых ситуаций для модуля интерпретаций."""
import unittest

from src.utils.numerology import calculate_all
from src.utils import interpretations as it


class TestCharacter(unittest.TestCase):
    def test_empty_sector(self):
        self.assertIn("пуст", it.get_character_interpretation(0).lower())

    def test_each_known_count_has_text(self):
        for n in range(1, 7):
            with self.subTest(n=n):
                self.assertTrue(it.get_character_interpretation(n).strip())

    def test_seven_and_more_collapse_to_type_7(self):
        base = it.get_character_interpretation(7)
        for n in (7, 8, 12):
            with self.subTest(n=n):
                self.assertEqual(it.get_character_interpretation(n), base)
        self.assertIn("1111111", base)


class TestEnergyHealthDependency(unittest.TestCase):
    def test_two_with_empty_health_is_deficit(self):
        self.assertIn("Дефицит", it.get_energy_interpretation(2, 0))

    def test_two_with_health_is_optimal(self):
        self.assertIn("Оптимальный", it.get_energy_interpretation(2, 1))

    def test_zero_is_deficit(self):
        self.assertIn("Дефицит", it.get_energy_interpretation(0, 0))

    def test_three_is_optimal(self):
        self.assertIn("Оптимальный", it.get_energy_interpretation(3, 0))

    def test_four_plus_is_surplus(self):
        self.assertIn("Профицит", it.get_energy_interpretation(4, 5))


class TestInterestBuckets(unittest.TestCase):
    def test_single_three_is_not_error_text(self):
        # краевая ситуация: одна тройка (count==1) должна давать осмысленный текст,
        # а не "промежуточное значение"
        text = it.get_interest_interpretation(1)
        self.assertNotIn("промежуточное", text)

    def test_zero_is_empty_bucket(self):
        self.assertIn("опор", it.get_interest_interpretation(0).lower())

    def test_three_plus_is_mentorship(self):
        self.assertIn("наставнич", it.get_interest_interpretation(3).lower())


class TestDutyMemoryBoundaries(unittest.TestCase):
    def test_duty_zero_and_one_same_bucket(self):
        self.assertEqual(it.get_duty_interpretation(0, 0), it.get_duty_interpretation(1, 0))

    def test_duty_two_plus_is_developed(self):
        self.assertIn("888", it.get_duty_interpretation(2, 0))

    def test_memory_zero_and_one_same_bucket(self):
        self.assertEqual(it.get_memory_interpretation(0, 0), it.get_memory_interpretation(1, 0))


class TestLuckCompensation(unittest.TestCase):
    def test_empty_luck_returns_text(self):
        self.assertTrue(it.get_luck_interpretation(0, 0, 1).strip())

    def test_counts_have_distinct_texts(self):
        texts = {it.get_luck_interpretation(n, 0, 1) for n in (0, 1, 2, 3)}
        self.assertEqual(len(texts), 4)


class TestDestinyNumber(unittest.TestCase):
    def test_all_known_numbers(self):
        for n in list(range(1, 10)) + [11]:
            with self.subTest(n=n):
                self.assertIn(f"ЧС {n}", it.get_destiny_number_interpretation(n))

    def test_unknown_number_fallback(self):
        self.assertIn("специфическая", it.get_destiny_number_interpretation(0))


class TestPurposeStability(unittest.TestCase):
    def test_purpose_energy_note_added_on_low_energy(self):
        with_note = it.get_purpose_interpretation(6, 0)
        without_note = it.get_purpose_interpretation(6, 3)
        self.assertIn("У этого человека дефицит энергии", with_note)
        self.assertNotIn("У этого человека дефицит энергии", without_note)

    def test_stability_buckets_nonempty(self):
        for n in (1, 4, 6):
            with self.subTest(n=n):
                self.assertTrue(it.get_stability_interpretation(n).strip())


class TestAggregators(unittest.TestCase):
    def test_all_interpretations_complete(self):
        r = calculate_all("18.08.1984")
        ints = it.get_all_interpretations(r)
        self.assertEqual(
            set(ints.keys()),
            {"character", "energy", "interest", "health", "logic",
             "labor", "luck", "duty", "memory"},
        )
        self.assertTrue(all(v.strip() for v in ints.values()))

    def test_additional_qualities_complete(self):
        r = calculate_all("18.08.1984")
        quals = it.get_additional_qualities(r)
        self.assertEqual(
            set(quals.keys()),
            {"life", "temperament", "family", "stability",
             "purpose", "transformation", "destiny_number"},
        )
        self.assertTrue(all(v.strip() for v in quals.values()))

    def test_no_interpretation_falls_to_placeholder(self):
        # На реальных датах не должно быть "промежуточное значение" в основных секторах
        for d in ["18.08.1984", "05.12.1990", "29.02.2004", "01.01.2000"]:
            r = calculate_all(d)
            for key, text in it.get_all_interpretations(r).items():
                with self.subTest(date=d, key=key):
                    self.assertNotIn("промежуточное значение", text)


if __name__ == "__main__":
    unittest.main()
