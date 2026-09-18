"""Режим проверки админа: /admin переключает между «админ», «пользователь без подписки»
и «пользователь с подпиской»."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src import access, admin_mode  # noqa: E402
from src.db.repositories import SubscriptionRepo, UserRepo  # noqa: E402
from tests.test_e2e import USER_ID, E2EBase  # noqa: E402

DATE = "18.08.1984"


def _datas(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class AdminModeBase(E2EBase):
    async def give_real_recurring_subscription(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            await SubscriptionRepo(s).apply_prodamus_payment(
                u.id,
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
                customer_phone="79998887766",
            )
            await s.commit()

    def last_markup(self):
        for m in reversed(self.session.requests):
            if getattr(m, "reply_markup", None) is not None:
                return m.reply_markup
        return None

    def result_buttons_text(self):
        return " ".join(b.text for row in self.last_markup().inline_keyboard for b in row)


class TestAdminPanel(AdminModeBase):
    async def test_panel_lists_modes(self):
        await self.feed_text("/admin")
        self.assertIn("Панель админа", self.session.last_text())
        datas = _datas(self.last_markup())
        self.assertEqual(datas[:3], ["adm:mode:admin", "adm:mode:free", "adm:mode:premium"])

    async def test_non_admin_cannot_open_or_switch(self):
        with patch("src.admin_mode.ADMIN_USER_IDS", set()):
            await self.feed_text("/admin")
            self.assertNotIn("SendMessage", self.session.names())
            await self.feed_callback("adm:mode:premium")
        self.assertEqual(admin_mode.get_mode(USER_ID), admin_mode.MODE_ADMIN)
        answer = next(m for m in self.session.requests if type(m).__name__ == "AnswerCallbackQuery")
        self.assertTrue(answer.show_alert)

    async def test_unknown_mode_rejected(self):
        await self.feed_callback("adm:mode:root")
        self.assertEqual(admin_mode.get_mode(USER_ID), admin_mode.MODE_ADMIN)
        with self.assertRaises(ValueError):
            admin_mode.set_mode(USER_ID, "root")


class TestFreeUserMode(AdminModeBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # У админа есть и реальная подписка, и PREMIUM_USER_IDS — режим должен их перекрыть.
        await self.give_real_recurring_subscription()
        access.PREMIUM_USER_IDS.add(USER_ID)
        await self.feed_callback("adm:mode:free")

    async def asyncTearDown(self):
        access.PREMIUM_USER_IDS.discard(USER_ID)
        await super().asyncTearDown()

    async def test_paid_sections_locked(self):
        self.session.clear()
        await self.feed_text(DATE)
        self.assertIn("🔒", self.result_buttons_text())
        self.session.clear()
        await self.feed_callback(f"qual:life:{DATE}")
        self.assertTrue(any("платная функция" in t for t in self.session.texts()))
        self.session.clear()
        await self.feed_callback(f"rep:{DATE}")
        self.assertNotIn("SendDocument", self.session.names())

    async def test_subscription_offer_instead_of_real_status(self):
        link = "https://pay.example/?x=1"
        self.session.clear()
        with patch("src.handlers.subscription.PAYMENTS_ENABLED", True), \
             patch("src.handlers.subscription.build_payment_link", return_value=link):
            await self.feed_callback("cab:sub")
        self.assertNotIn("Подписка активна", self.session.last_text())
        self.assertEqual(self.last_markup().inline_keyboard[0][0].url, link)

    async def test_real_subscription_not_cancellable(self):
        set_activity = AsyncMock(return_value={"ok": True})
        with patch("src.handlers.subscription.set_activity", set_activity):
            await self.feed_text("/unsubscribe")
            await self.feed_callback("sub:ask")
            await self.feed_callback("sub:cancel")
        set_activity.assert_not_awaited()
        async with self.factory() as s:
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
            self.assertIsNone((await SubscriptionRepo(s).get(u.id)).cancelled_at)

    async def test_admin_commands_denied(self):
        self.session.clear()
        await self.feed_text(f"/grant {USER_ID}")
        self.assertIn("только администраторам", self.session.last_text())
        await self.feed_text(f"/payments {USER_ID}")
        self.assertIn("только администраторам", self.session.last_text())

    async def test_switch_back_restores_admin(self):
        await self.feed_callback("adm:mode:admin")
        self.session.clear()
        await self.feed_text(DATE)
        self.assertNotIn("🔒", self.result_buttons_text())
        await self.feed_text(f"/grant {USER_ID}")
        self.assertIn("Премиум выдан", self.session.last_text())


class TestPremiumUserMode(AdminModeBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.feed_callback("adm:mode:premium")  # у админа реальной подписки нет

    async def test_everything_unlocked(self):
        self.session.clear()
        await self.feed_text(DATE)
        self.assertNotIn("🔒", self.result_buttons_text())
        self.session.clear()
        await self.feed_callback(f"qual:temperament:{DATE}")
        self.assertIn("ТЕМПЕРАМЕНТ", self.session.last_text())
        self.session.clear()
        await self.feed_callback(f"rep:{DATE}")
        self.assertIn("SendDocument", self.session.names())

    async def test_subscription_is_simulated(self):
        self.session.clear()
        await self.feed_callback("cab:sub")
        self.assertIn("Режим проверки", self.session.last_text())
        self.assertNotIn("sub:ask", _datas(self.last_markup()))
        self.assertIn("cab:menu", _datas(self.last_markup()))

    async def test_no_real_subscription_written(self):
        await self.feed_callback(f"rep:{DATE}")
        async with self.factory() as s:
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
            self.assertIsNone(await SubscriptionRepo(s).get(u.id))


class TestModeIsolation(unittest.TestCase):
    def tearDown(self):
        admin_mode.reset_all()

    def test_mode_ignored_for_non_admin(self):
        with patch("src.admin_mode.ADMIN_USER_IDS", {1}):
            admin_mode.set_mode(1, admin_mode.MODE_FREE)
            self.assertIsNone(admin_mode.simulated_premium(2))
            self.assertFalse(admin_mode.simulated_premium(1))
            self.assertFalse(admin_mode.has_admin_rights(1))

    def test_mode_dropped_when_removed_from_admins(self):
        with patch("src.admin_mode.ADMIN_USER_IDS", {1}):
            admin_mode.set_mode(1, admin_mode.MODE_PREMIUM)
        with patch("src.admin_mode.ADMIN_USER_IDS", set()):
            self.assertIsNone(admin_mode.simulated_premium(1))


if __name__ == "__main__":
    unittest.main()
