"""Тесты подписи Prodamus (совместимость с PHP Hmac::create)."""
import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.payments.hmac_sign import create_signature, verify_signature  # noqa: E402

SECRET = "test_secret_key"


class TestCreateSignature(unittest.TestCase):
    def test_slashes_escaped_like_php(self):
        """PHP json_encode экранирует "/" — подпись должна это учитывать."""
        with_url = {"urlNotification": "https://example.ru/hook"}
        escaped = {"urlNotification": "https:\\/\\/example.ru\\/hook"}
        # Если бы слэши не экранировались, подписи совпали бы с "неэкранированным" вариантом.
        self.assertNotEqual(create_signature(with_url, SECRET), create_signature(escaped, SECRET))

    def test_key_order_does_not_matter(self):
        a = {"b": "2", "a": "1", "c": "3"}
        b = {"c": "3", "a": "1", "b": "2"}
        self.assertEqual(create_signature(a, SECRET), create_signature(b, SECRET))

    def test_nested_dicts_sorted_recursively(self):
        a = {"sub": {"z": "1", "a": "2"}, "x": "3"}
        b = {"x": "3", "sub": {"a": "2", "z": "1"}}
        self.assertEqual(create_signature(a, SECRET), create_signature(b, SECRET))

    def test_scalar_casting_matches_php_strval(self):
        typed = {"flag_on": True, "flag_off": False, "empty": None, "num": 42}
        strings = {"flag_on": "1", "flag_off": "", "empty": "", "num": "42"}
        self.assertEqual(create_signature(typed, SECRET), create_signature(strings, SECRET))

    def test_signature_key_excluded(self):
        data = {"order_id": "1"}
        with_sig = {"order_id": "1", "signature": "deadbeef"}
        self.assertEqual(create_signature(data, SECRET), create_signature(with_sig, SECRET))

    def test_cyrillic_not_escaped(self):
        """ensure_ascii=False: кириллица идёт в подпись как есть, а не \\uXXXX."""
        self.assertNotEqual(
            create_signature({"name": "Подписка"}, SECRET),
            create_signature({"name": "\\u041f\\u043e\\u0434\\u043f\\u0438\\u0441\\u043a\\u0430"}, SECRET),
        )

    def test_list_and_indexed_dict_differ(self):
        """PHP-массив 0..n-1 — это список; объект с теми же ключами даёт другую подпись."""
        as_list = {"products": [{"name": "A"}]}
        as_dict = {"products": {"0": {"name": "A"}}}
        self.assertNotEqual(create_signature(as_list, SECRET), create_signature(as_dict, SECRET))


class TestVerifySignature(unittest.TestCase):
    def setUp(self):
        self.data = {"order_id": "42", "sum": "299.00"}
        self.sig = create_signature(self.data, SECRET)

    def test_valid(self):
        self.assertTrue(verify_signature(self.data, SECRET, self.sig))

    def test_case_insensitive(self):
        self.assertTrue(verify_signature(self.data, SECRET, self.sig.upper()))

    def test_whitespace_tolerated(self):
        self.assertTrue(verify_signature(self.data, SECRET, f"  {self.sig}\n"))

    def test_tampered_payload_rejected(self):
        self.assertFalse(verify_signature({**self.data, "sum": "1.00"}, SECRET, self.sig))

    def test_wrong_secret_rejected(self):
        self.assertFalse(verify_signature(self.data, "other_secret", self.sig))

    def test_missing_signature_rejected(self):
        self.assertFalse(verify_signature(self.data, SECRET, None))
        self.assertFalse(verify_signature(self.data, SECRET, ""))


if __name__ == "__main__":
    unittest.main()
