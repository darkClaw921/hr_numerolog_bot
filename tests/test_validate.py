"""Тесты проверки полноты результатов расчёта (validate_results)."""
import unittest

from src.utils.numerology import calculate_all, validate_results


class TestValidateResults(unittest.TestCase):
    def test_valid_passes(self):
        # Корректный результат не должен бросать исключение.
        results = calculate_all("18.08.1984")
        validate_results(results)  # не должно бросить

    def test_missing_coefficient_raises(self):
        results = calculate_all("18.08.1984")
        del results["sector_family"]
        with self.assertRaises(ValueError):
            validate_results(results)

    def test_none_coefficient_raises(self):
        results = calculate_all("18.08.1984")
        results["sector_life"] = None
        with self.assertRaises(ValueError):
            validate_results(results)

    def test_incomplete_matrix_raises(self):
        results = calculate_all("18.08.1984")
        results["matrix"].pop(9)
        with self.assertRaises(ValueError):
            validate_results(results)

    def test_missing_destiny_raises(self):
        results = calculate_all("18.08.1984")
        results["destiny_number"] = None
        with self.assertRaises(ValueError):
            validate_results(results)
