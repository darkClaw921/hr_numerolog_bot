"""Тесты разбора тела уведомления Prodamus в PHP-подобную структуру."""
import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.payments.formdata import parse_php_form, php_urlencode  # noqa: E402
from src.payments.hmac_sign import create_signature  # noqa: E402


class TestParsePhpForm(unittest.TestCase):
    def test_flat_pairs(self):
        self.assertEqual(parse_php_form("order_id=42&sum=299.00"), {"order_id": "42", "sum": "299.00"})

    def test_nested_dict(self):
        parsed = parse_php_form("subscription[id]=7&subscription[active_manager]=1")
        self.assertEqual(parsed, {"subscription": {"id": "7", "active_manager": "1"}})

    def test_indexed_keys_become_list(self):
        parsed = parse_php_form("products[0][name]=A&products[1][name]=B")
        self.assertEqual(parsed, {"products": [{"name": "A"}, {"name": "B"}]})

    def test_sparse_indexes_stay_dict(self):
        """Пропуск индекса — это уже не PHP-список, оставляем объектом."""
        self.assertEqual(parse_php_form("products[1][name]=B"), {"products": {"1": {"name": "B"}}})

    def test_empty_brackets_autoincrement(self):
        self.assertEqual(parse_php_form("tags[]=a&tags[]=b"), {"tags": ["a", "b"]})

    def test_blank_values_kept(self):
        self.assertEqual(parse_php_form("customer_extra=&order_id=1"),
                         {"customer_extra": "", "order_id": "1"})

    def test_percent_and_plus_decoded(self):
        self.assertEqual(parse_php_form("name=%D0%90+%D0%91"), {"name": "А Б"})

    def test_values_stay_strings(self):
        parsed = parse_php_form("sum=299&subscription[id]=7")
        self.assertIsInstance(parsed["sum"], str)
        self.assertIsInstance(parsed["subscription"]["id"], str)


class TestRoundTrip(unittest.TestCase):
    SAMPLE = {
        "date": "2026-09-07T12:00:00+03:00",
        "order_id": "12-ab34cd56",
        "order_num": "5",
        "sum": "299.00",
        "customer_phone": "79998887766",
        "customer_email": "user@example.ru",
        "customer_extra": "tg:555",
        "payment_type": "Оплата картой",
        "payment_status": "success",
        "products": [{"name": "Подписка «Премиум»", "price": "299.00", "quantity": "1"}],
        "subscription": {
            "id": "7",
            "name": "Премиум",
            "active": "1",
            "active_manager": "1",
            "active_user": "1",
            "cost": "299.00",
            "date_next_payment": "2026-10-07 12:00:00",
            "payment_num": "1",
        },
    }

    def test_encode_parse_roundtrip(self):
        self.assertEqual(parse_php_form(php_urlencode(self.SAMPLE)), self.SAMPLE)

    def test_signature_survives_transport(self):
        """Подпись, посчитанная до кодирования, сходится после разбора — основа проверки вебхука."""
        secret = "s3cret"
        before = create_signature(self.SAMPLE, secret)
        after = create_signature(parse_php_form(php_urlencode(self.SAMPLE)), secret)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
