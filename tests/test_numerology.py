"""Тесты краевых ситуаций для модуля расчётов numerology."""
import unittest

from src.utils.numerology import (
    parse_date,
    sum_digits,
    calculate_first_additional,
    calculate_third_additional,
    calculate_destiny_number,
    calculate_all,
)


class TestParseDate(unittest.TestCase):
    def test_valid_date(self):
        self.assertEqual(parse_date("18.08.1984"), (18, 8, 1984))

    def test_leading_zero_day(self):
        self.assertEqual(parse_date("05.12.1990"), (5, 12, 1990))

    def test_invalid_format_raises(self):
        for bad in ["1984.08.18", "18/08/1984", "18-08-1984", "abc", "", "18.08.84"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_date(bad)

    def test_impossible_date_raises(self):
        for bad in ["32.01.2000", "29.02.2001", "00.00.0000"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_date(bad)

    def test_leap_day_valid(self):
        self.assertEqual(parse_date("29.02.2004"), (29, 2, 2004))


class TestSumDigits(unittest.TestCase):
    def test_single_digit_unchanged(self):
        self.assertEqual(sum_digits(7), 7)

    def test_zero(self):
        self.assertEqual(sum_digits(0), 0)

    def test_reduces_to_single(self):
        self.assertEqual(sum_digits(39), 3)   # 3+9=12 -> 1+2=3
        self.assertEqual(sum_digits(99), 9)   # 9+9=18 -> 1+8=9


class TestThirdAdditional(unittest.TestCase):
    def test_leading_zero_day_uses_nonzero_digit(self):
        # 05.12.1990: first=27, первая значащая цифра дня = 5 -> 27 - 2*5 = 17
        first = calculate_first_additional("05.12.1990")
        self.assertEqual(first, 27)
        self.assertEqual(calculate_third_additional(first, 5), 17)

    def test_can_be_negative(self):
        # краевая ситуация: третье доп. число может стать отрицательным
        self.assertEqual(calculate_third_additional(5, 9), 5 - 18)


class TestDestinyNumber(unittest.TestCase):
    def test_master_number_11_preserved(self):
        self.assertEqual(calculate_destiny_number("19.09.1981"), 11)

    def test_single_digit_first_additional(self):
        # 01.01.2000: сумма цифр = 4 (однозначное) -> остаётся 4
        self.assertEqual(calculate_destiny_number("01.01.2000"), 4)

    def test_reduces_to_single_digit(self):
        self.assertEqual(calculate_destiny_number("18.08.1984"), 3)

    def test_in_valid_range(self):
        for d in ["18.08.1984", "05.12.1990", "29.02.2004", "09.09.1999"]:
            with self.subTest(d=d):
                dn = calculate_destiny_number(d)
                self.assertTrue(dn == 11 or 1 <= dn <= 9)


class TestCalculateAll(unittest.TestCase):
    def test_keys_present(self):
        r = calculate_all("18.08.1984")
        for key in [
            "date", "first_additional", "second_additional", "third_additional",
            "fourth_additional", "matrix", "sector_temperament", "sector_life",
            "sector_purpose", "sector_family", "destiny_number",
        ]:
            self.assertIn(key, r)

    def test_matrix_has_all_sectors(self):
        r = calculate_all("18.08.1984")
        self.assertEqual(set(r["matrix"].keys()), set(range(1, 10)))

    def test_zeros_excluded_from_matrix(self):
        # 01.01.2000 содержит много нулей — нулей в матрице быть не должно
        r = calculate_all("01.01.2000")
        for sector, numbers in r["matrix"].items():
            with self.subTest(sector=sector):
                self.assertTrue(all(n == sector for n in numbers))
        self.assertNotIn(0, r["matrix"])

    def test_coefficients_nonnegative(self):
        r = calculate_all("29.02.2004")
        for key in ["sector_temperament", "sector_life", "sector_purpose", "sector_family"]:
            self.assertGreaterEqual(r[key], 0)


if __name__ == "__main__":
    unittest.main()
