"""
Тесты обработки уведомлений Prodamus: подпись, идемпотентность, продление, отмена.

Проверяют и чистую логику (`apply_notification`), и HTTP-слой вебхука.
Формат уведомления сверен с реальным: номер заказа Prodamus приходит в `order_id`,
выданный ботом идентификатор — в `order_num`, даты без зоны — московское время.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("PRODAMUS_SECRET_KEY", "webhook_test_secret")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.db.base import Base  # noqa: E402
from src.db.models import Payment  # noqa: E402
from src.db.repositories import PaymentIntentRepo, PaymentRepo, SubscriptionRepo, UserRepo  # noqa: E402
from src.payments import service  # noqa: E402
from src.payments.formdata import php_urlencode  # noqa: E402
from src.payments.hmac_sign import create_signature  # noqa: E402

SECRET = os.environ["PRODAMUS_SECRET_KEY"]
TELEGRAM_ID = 555
# Идентификатор, который выдал бот (приходит обратно в order_num).
ORDER_ID = "1-abc123"
# Номер заказа на стороне Prodamus (приходит в order_id).
PRODAMUS_ORDER_ID = "48808966"
# Даты Prodamus без зоны — московское время (UTC+3).
MSK_OFFSET = timedelta(hours=3)


def notification(
    *,
    order_num: str = ORDER_ID,
    order_id: str = PRODAMUS_ORDER_ID,
    payment_status: str = "success",
    payment_num: str = "1",
    date_next_payment: str | None = "2026-10-07 12:00:00",
    active_manager: str = "1",
    date: str = "2026-09-07T12:00:00+03:00",
    customer_extra: str = f"tg:{TELEGRAM_ID}",
) -> dict:
    """Уведомление в том виде, в каком его присылает Prodamus для подписки."""
    subscription = {
        "id": "7",
        "name": "Премиум",
        "active_manager": active_manager,
        "active_user": "1",
        "cost": "299.00",
        "first_payment_discount": "100.00",
        "payment_num": payment_num,
    }
    if date_next_payment is not None:
        subscription["date_next_payment"] = date_next_payment
    return {
        "date": date,
        "order_id": order_id,
        "order_num": order_num,
        "sum": "199.00",
        "customer_phone": "79998887766",
        "customer_email": "user@example.ru",
        "customer_extra": customer_extra,
        "payment_type": "Оплата картой",
        "payment_status": payment_status,
        "products": [{"name": "Подписка", "price": "199.00", "quantity": "1", "sum": "199.00"}],
        "subscription": subscription,
    }


class TestParseProdamusDatetime(unittest.TestCase):
    def test_naive_date_is_moscow_time(self):
        self.assertEqual(
            service.parse_prodamus_datetime("2026-10-15 19:35:23"),
            datetime(2026, 10, 15, 16, 35, 23),
        )

    def test_iso_with_zone_converted_by_its_zone(self):
        self.assertEqual(
            service.parse_prodamus_datetime("2026-09-15T19:36:26+03:00"),
            datetime(2026, 9, 15, 16, 36, 26),
        )

    def test_date_only(self):
        self.assertEqual(service.parse_prodamus_datetime("2026-10-15"), datetime(2026, 10, 14, 21, 0))

    def test_empty_and_garbage(self):
        self.assertIsNone(service.parse_prodamus_datetime(""))
        self.assertIsNone(service.parse_prodamus_datetime("не дата"))


class WebhookTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self._tmp.name}")
        async with self.engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.commit()
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.factory() as session:
            user = await UserRepo(session).get_or_create(telegram_id=TELEGRAM_ID)
            self.user_id = user.id
            await PaymentIntentRepo(session).create(user.id, ORDER_ID, amount_rub=199)
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        os.unlink(self._tmp.name)

    async def apply(self, data: dict) -> service.ApplyResult:
        async with self.factory() as session:
            result = await service.apply_notification(session, data, php_urlencode(data))
            await session.commit()
            return result

    async def subscription(self):
        async with self.factory() as session:
            return await SubscriptionRepo(session).get(self.user_id)

    async def payments(self) -> list[Payment]:
        async with self.factory() as session:
            return await PaymentRepo(session).list_by_user(self.user_id, limit=50)


class TestApplyNotification(WebhookTestBase):
    async def test_first_payment_activates_premium(self):
        result = await self.apply(notification())
        self.assertEqual(result.outcome, service.OUTCOME_ACTIVATED)
        self.assertEqual(result.telegram_id, TELEGRAM_ID)
        self.assertEqual(result.order_id, ORDER_ID)

        sub = await self.subscription()
        self.assertTrue(sub.is_premium)
        self.assertTrue(sub.prodamus_active)
        self.assertEqual(sub.provider, "prodamus")
        self.assertEqual(sub.prodamus_subscription_id, "7")
        # Срок = дата следующего списания (МСК → UTC) + запас на повторные попытки.
        self.assertEqual(sub.expires_at, datetime(2026, 10, 7, 12, 0) - MSK_OFFSET + timedelta(days=2))

        events = await self.payments()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "initial")
        self.assertEqual(events[0].status, "success")
        self.assertEqual(events[0].order_id, PRODAMUS_ORDER_ID)
        self.assertEqual(events[0].order_num, ORDER_ID)

    async def test_intent_marked_paid(self):
        await self.apply(notification())
        async with self.factory() as session:
            intent = await PaymentIntentRepo(session).get_by_order_id(ORDER_ID)
        self.assertIsNotNone(intent.paid_at)

    async def test_matched_by_order_num_without_customer_extra(self):
        """Регрессия: наш идентификатор Prodamus возвращает в order_num, а не в order_id."""
        result = await self.apply(notification(customer_extra=""))
        self.assertEqual(result.outcome, service.OUTCOME_ACTIVATED)
        self.assertEqual(result.telegram_id, TELEGRAM_ID)

    async def test_duplicate_delivery_is_idempotent(self):
        data = notification()
        await self.apply(data)
        first = await self.subscription()

        result = await self.apply(data)
        self.assertEqual(result.outcome, service.OUTCOME_DUPLICATE)

        second = await self.subscription()
        self.assertEqual(first.expires_at, second.expires_at)
        self.assertEqual(len(await self.payments()), 1)

    async def test_renewal_extends_subscription(self):
        await self.apply(notification())
        result = await self.apply(
            notification(
                order_id="48900000",
                payment_num="2",
                date="2026-10-07T12:00:00+03:00",
                date_next_payment="2026-11-07 12:00:00",
            )
        )
        self.assertEqual(result.outcome, service.OUTCOME_RENEWED)

        sub = await self.subscription()
        self.assertEqual(sub.expires_at, datetime(2026, 11, 7, 12, 0) - MSK_OFFSET + timedelta(days=2))
        events = await self.payments()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].kind, "renewal")

    async def test_renewal_without_next_date_extends_from_current_end(self):
        """Без date_next_payment продлеваем от конца периода, а не от «сейчас»."""
        await self.apply(notification(date_next_payment=None))
        first = await self.subscription()
        await self.apply(
            notification(payment_num="2", date="2026-10-01T10:00:00+03:00", date_next_payment=None)
        )
        second = await self.subscription()
        self.assertEqual(second.expires_at, first.expires_at + timedelta(days=31))

    async def test_failed_payment_keeps_expiry(self):
        await self.apply(notification())
        before = await self.subscription()

        result = await self.apply(
            notification(payment_status="failed", payment_num="2", date="2026-10-07T12:00:00+03:00")
        )
        self.assertEqual(result.outcome, service.OUTCOME_FAILED)

        after = await self.subscription()
        self.assertEqual(before.expires_at, after.expires_at)
        self.assertTrue(after.is_premium)
        self.assertEqual(len(await self.payments()), 2)

    async def test_cancellation_keeps_access_until_period_end(self):
        await self.apply(notification())
        result = await self.apply(
            notification(
                payment_status="",
                active_manager="0",
                payment_num="1",
                date="2026-09-08T12:00:00+03:00",
            )
        )
        self.assertEqual(result.outcome, service.OUTCOME_CANCELLED)

        sub = await self.subscription()
        self.assertFalse(sub.prodamus_active)
        self.assertIsNotNone(sub.cancelled_at)
        # Доступ не снимаем: оплаченный период дорабатывает до конца.
        self.assertTrue(sub.is_premium)
        async with self.factory() as session:
            self.assertTrue(await SubscriptionRepo(session).is_active(self.user_id))

    async def test_unknown_order_is_recorded_without_activation(self):
        foreign = notification(order_num="not-mine", order_id="1", customer_extra="")
        result = await self.apply(foreign)
        self.assertEqual(result.outcome, service.OUTCOME_UNMATCHED)
        self.assertIsNone(await self.subscription())

        async with self.factory() as session:
            payment = await PaymentRepo(session).get_by_event_key(service.build_event_key(foreign))
        self.assertIsNotNone(payment)
        self.assertIsNone(payment.user_id)

    async def test_matching_by_customer_extra(self):
        """Автосписание без нашего идентификатора находит пользователя по customer_extra."""
        result = await self.apply(notification(order_num="foreign-1"))
        self.assertEqual(result.outcome, service.OUTCOME_ACTIVATED)
        self.assertEqual(result.telegram_id, TELEGRAM_ID)


class TestWebhookHttp(WebhookTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from aiohttp.test_utils import TestClient, TestServer

        from src.payments import webhook

        # Вебхук ходит в БД через общую фабрику сессий — подменяем её на тестовую.
        self._orig_factory = webhook.async_session_factory
        webhook.async_session_factory = self.factory
        # src.config читает окружение один раз при импорте, а порядок импорта модулей
        # в discover не гарантирован — задаём секрет прямо в модуле вебхука.
        self._orig_secret = webhook.PRODAMUS_SECRET_KEY
        webhook.PRODAMUS_SECRET_KEY = SECRET
        self._webhook = webhook

        self.client = TestClient(TestServer(webhook.create_webhook_app(bot=None)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self._webhook.async_session_factory = self._orig_factory
        self._webhook.PRODAMUS_SECRET_KEY = self._orig_secret
        await super().asyncTearDown()

    async def post(self, data: dict, signature: str | None = None):
        body = php_urlencode(data)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Sign": signature if signature is not None else create_signature(data, SECRET),
        }
        return await self.client.post(self._webhook.PRODAMUS_WEBHOOK_PATH, data=body, headers=headers)

    async def post_multipart(self, data: dict, signature: str | None = None):
        """Уведомление в multipart/form-data с плоскими ключами — Prodamus поддерживает и этот формат."""
        import aiohttp

        from src.payments.formdata import php_form_pairs

        writer = aiohttp.MultipartWriter("form-data")
        for key, value in php_form_pairs(data):
            part = writer.append(value)
            part.set_content_disposition("form-data", name=key)
        headers = {"Sign": signature if signature is not None else create_signature(data, SECRET)}
        return await self.client.post(self._webhook.PRODAMUS_WEBHOOK_PATH, data=writer, headers=headers)

    async def test_valid_signature_activates(self):
        response = await self.post(notification())
        self.assertEqual(response.status, 200)
        sub = await self.subscription()
        self.assertTrue(sub.is_premium)

    async def test_multipart_notification_activates(self):
        """Подпись должна сходиться и в multipart/form-data."""
        response = await self.post_multipart(notification())
        self.assertEqual(response.status, 200)
        sub = await self.subscription()
        self.assertTrue(sub.is_premium)
        self.assertEqual(len(await self.payments()), 1)

    async def test_multipart_invalid_signature_rejected(self):
        response = await self.post_multipart(notification(), signature="0" * 64)
        self.assertEqual(response.status, 400)
        self.assertIsNone(await self.subscription())

    async def test_invalid_signature_rejected(self):
        response = await self.post(notification(), signature="0" * 64)
        self.assertEqual(response.status, 400)
        self.assertIsNone(await self.subscription())
        self.assertEqual(await self.payments(), [])

    async def test_missing_signature_rejected(self):
        body = php_urlencode(notification())
        response = await self.client.post(
            self._webhook.PRODAMUS_WEBHOOK_PATH,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(response.status, 400)

    async def test_repeated_delivery_returns_200_once_applied(self):
        data = notification()
        self.assertEqual((await self.post(data)).status, 200)
        first = await self.subscription()
        self.assertEqual((await self.post(data)).status, 200)
        second = await self.subscription()
        self.assertEqual(first.expires_at, second.expires_at)
        self.assertEqual(len(await self.payments()), 1)

    async def test_oversized_body_rejected(self):
        data = notification()
        data["customer_extra"] = "x" * (self._webhook.MAX_BODY_BYTES + 10)
        response = await self.post(data)
        self.assertIn(response.status, (400, 413))
        self.assertIsNone(await self.subscription())

    async def test_healthcheck(self):
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
