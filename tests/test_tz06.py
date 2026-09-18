"""
Тесты доработок по ТЗ 06: навигация «Назад», кабинет (/menu, история, подписка,
бонус), переименования, скрытие «Трансформации», коэффициент 3/6/9, реферальный бонус.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.db.repositories import (  # noqa: E402
    PaymentIntentRepo,
    PersonRepo,
    ReferralRepo,
    SubscriptionRepo,
    UserRepo,
)
from src.formatting import build_full_report, destiny_calculation, format_quality_interpretation  # noqa: E402
from src.handlers.common import BOT_COMMANDS  # noqa: E402
from src.keyboards import create_back_keyboard, create_result_keyboard, split_callback  # noqa: E402
from src.payments import service  # noqa: E402
from src.utils.interpretations import get_additional_qualities, get_stability_interpretation  # noqa: E402
from src.utils.numerology import calculate_all, calculate_destiny_number  # noqa: E402
from tests.test_e2e import USER_ID, E2EBase  # noqa: E402

DATE = "18.08.1984"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _buttons(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def _texts(markup):
    return [btn.text for btn in _buttons(markup)]


def _datas(markup):
    return [btn.callback_data for btn in _buttons(markup)]


class TestResultKeyboard(unittest.TestCase):
    def test_renamed_buttons_and_hidden_transformation(self):
        texts = _texts(create_result_keyboard(DATE, is_premium=True))
        self.assertIn("Число Судьбы", texts)          # п. 1
        self.assertIn("Темперамент", texts)           # п. 9
        self.assertNotIn("ПЛОТСКОЕ", " ".join(texts))
        self.assertFalse(any("Трансформ" in t for t in texts))  # п. 11

    def test_no_divider(self):
        # п. 7: пустая кнопка-разделитель убрана.
        markup = create_result_keyboard(DATE, is_premium=False)
        self.assertNotIn("noop", _datas(markup))
        self.assertFalse(any(set(t) == {"━"} for t in _texts(markup)))

    def test_search_screen_has_save_and_cabinet(self):
        datas = _datas(create_result_keyboard(DATE, is_premium=False))
        self.assertIn(f"save:{DATE}", datas)
        self.assertIn("cab:menu", datas)

    def test_profile_screen_back_and_cabinet_without_save(self):
        # п. 4-6: профиль сохранённого — «Назад» к людям, кабинет, без «Сохранить».
        datas = _datas(create_result_keyboard(DATE, is_premium=False, person_id=42))
        self.assertIn("cab:people", datas)
        self.assertIn("cab:menu", datas)
        self.assertFalse(any(d.startswith("save:") for d in datas))
        # Все разделы профиля несут id профиля — «Назад» из них вернёт в профиль.
        for prefix in ("sec:", "qual:", "cmb:", "rep:"):
            self.assertTrue(all(d.endswith(":42") for d in datas if d.startswith(prefix)), prefix)

    def test_back_keyboard(self):
        self.assertEqual(_datas(create_back_keyboard(DATE, 42)), [f"bk:{DATE}:42"])
        self.assertIn("профиль", _texts(create_back_keyboard(DATE, 42))[0])
        self.assertEqual(_datas(create_back_keyboard(DATE)), [f"bk:{DATE}"])

    def test_split_callback(self):
        self.assertEqual(split_callback(f"qual:life:{DATE}:7", 3), (["qual", "life", DATE], 7))
        self.assertEqual(split_callback(f"qual:life:{DATE}", 3), (["qual", "life", DATE], None))


class TestCoefficients(unittest.TestCase):
    def test_stability_is_row_369(self):
        # п. 12: «Привычки/Стабильность» — отдельный коэффициент 3/6/9, а не копия «Цели».
        for date in ("18.08.1984", "05.12.1990", "29.02.2004", "01.01.2000", "11.11.1911"):
            r = calculate_all(date)
            expected = sum(len(r["matrix"][s]) for s in (3, 6, 9))
            self.assertEqual(r["sector_stability"], expected, date)
            self.assertEqual(get_additional_qualities(r)["stability"], get_stability_interpretation(expected))

    def test_quality_buckets_cover_all_values(self):
        # Ни одно значение коэффициента не должно падать в заглушку «промежуточное значение».
        r = calculate_all(DATE)
        for value in range(0, 20):
            r2 = dict(r, sector_life=value, sector_temperament=value, sector_family=value,
                      sector_purpose=value, sector_stability=value)
            for key, text in get_additional_qualities(r2).items():
                if key == "transformation":
                    continue
                with self.subTest(key=key, value=value):
                    self.assertNotIn("промежуточное значение", text)

    def test_destiny_calculation_matches_tz_example(self):
        self.assertEqual(
            destiny_calculation(DATE, 3),
            "1+8+0+8+1+9+8+4 = 39 → 3+9 = 12 → 1+2 = 3",
        )

    def test_destiny_calculation_consistent_with_algorithm(self):
        start = datetime(1940, 1, 1)
        for offset in range(0, 365 * 80, 7):
            date = (start + timedelta(days=offset)).strftime("%d.%m.%Y")
            with self.subTest(date=date):
                self.assertIsNotNone(destiny_calculation(date, calculate_destiny_number(date)))

    def test_quality_screen_has_description(self):
        r = calculate_all(DATE)
        text = format_quality_interpretation("destiny_number", get_additional_qualities(r)["destiny_number"], r)
        self.assertIn("профессиональную ориентацию", text)
        self.assertIn("Как вычислить", text)

    def test_report_escapes_person_label(self):
        html = build_full_report(calculate_all(DATE), "<Иван>", [])
        self.assertIn("&lt;Иван&gt;", html)


class TestBotCommands(unittest.TestCase):
    def test_menu_commands(self):
        # п. 2: в кнопке «Меню» — /start и /menu.
        self.assertEqual([c.command for c in BOT_COMMANDS], ["start", "menu"])


class TestNavigationE2E(E2EBase):
    async def _save_person(self, date, name):
        await self.feed_callback("cab:add")
        await self.feed_text(date)
        await self.feed_text(name)
        await self.feed_callback("add:skip")
        async with self.factory() as s:
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
            return (await PersonRepo(s).list(u.id))[0].id

    def _last_markup(self):
        for m in reversed(self.session.requests):
            if getattr(m, "reply_markup", None) is not None:
                return m.reply_markup
        return None

    async def test_menu_command_opens_cabinet(self):
        await self.feed_text("/menu")
        self.assertIn("Личный кабинет", self.session.last_text())
        self.assertIn("cab:ref", _datas(self._last_markup()))

    async def test_saved_date_hides_save_button(self):
        pid = await self._save_person("09.05.1991", "Иван")
        self.session.clear()
        await self.feed_text("09.05.1991")
        datas = _datas(self._last_markup())
        self.assertFalse(any(d.startswith("save:") for d in datas))
        self.assertIn(f"sec:character:09.05.1991:{pid}", datas)
        self.assertIn("Иван", self.session.last_text())

    async def test_profile_quality_back_returns_to_profile(self):
        pid = await self._save_person("09.05.1991", "Иван")
        self.session.clear()
        await self.feed_callback(f"pers:{pid}")
        self.assertIn("Иван", self.session.last_text())

        self.session.clear()
        await self.feed_callback(f"qual:destiny_number:09.05.1991:{pid}")
        self.assertIn("ЧИСЛО СУДЬБЫ", self.session.last_text())
        self.assertEqual(_datas(self._last_markup()), [f"bk:09.05.1991:{pid}"])

        self.session.clear()
        await self.feed_callback(f"bk:09.05.1991:{pid}")
        self.assertIn("Иван", self.session.last_text())
        self.assertIn("cab:people", _datas(self._last_markup()))

    async def test_combinations_have_back_button(self):
        await self.feed_text(f"/grant {USER_ID}")
        self.session.clear()
        await self.feed_callback(f"cmb:{DATE}")
        self.assertIn(f"bk:{DATE}", _datas(self._last_markup()))

    async def test_paywall_answers_callback_once(self):
        # Повторный answerCallbackQuery Telegram отклоняет — пейволл бы не показался.
        await self.feed_callback(f"qual:life:{DATE}")
        self.assertEqual(self.session.names().count("AnswerCallbackQuery"), 1)
        self.assertTrue(any("подписк" in t.lower() for t in self.session.texts()))
        self.assertIn(f"bk:{DATE}", _datas(self._last_markup()))

    async def test_hidden_transformation_callback(self):
        await self.feed_callback(f"qual:transformation:{DATE}")
        self.assertFalse(any("ТРАНСФОРМАЦИЯ" in t for t in self.session.texts()))

    async def test_history_lists_people_and_dates(self):
        pid = await self._save_person("09.05.1991", "Иван")
        await self.feed_callback(f"pers:{pid}")
        await self.feed_text(DATE)
        await self.feed_text(DATE)  # повтор не дублируется
        self.session.clear()
        await self.feed_callback("cab:history")
        datas = _datas(self._last_markup())
        self.assertEqual(datas, [f"bk:{DATE}", f"pers:{pid}", "cab:menu"])

    async def test_subscription_screen_back_and_cancel(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            sub = await SubscriptionRepo(s).apply_prodamus_payment(
                u.id, expires_at=_now() + timedelta(days=30), customer_phone="79998887766"
            )
            await s.commit()
        await self.feed_callback("cab:sub")
        datas = _datas(self._last_markup())
        self.assertIn("sub:ask", datas)   # п. 8.3.1
        self.assertIn("cab:menu", datas)  # п. 3.2

        self.session.clear()
        await self.feed_callback("sub:ask")
        self.assertIn("sub:cancel", _datas(self._last_markup()))

        self.session.clear()
        with patch("src.handlers.subscription.set_activity", AsyncMock(return_value={"ok": True})):
            await self.feed_callback("sub:cancel")
        self.assertIn("Автопродление отключено", self.session.last_text())
        async with self.factory() as s:
            sub = await SubscriptionRepo(s).get(u.id)
            self.assertIsNotNone(sub.cancelled_at)

    async def test_referral_screen_has_link(self):
        await self.feed_callback("cab:ref")
        async with self.factory() as s:
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
        self.assertIn(f"https://t.me/numbot?start=ref_{u.id}", self.session.last_text())


class TestReferralE2E(E2EBase):
    async def test_start_with_referral_attaches_friend(self):
        async with self.factory() as s:
            referrer = await UserRepo(s).get_or_create(telegram_id=999)
            await s.commit()
        await self.feed_text(f"/start ref_{referrer.id}")
        async with self.factory() as s:
            me = await UserRepo(s).get_by_telegram_id(USER_ID)
            referral = await ReferralRepo(s).get_by_referred(me.id)
        self.assertIsNotNone(referral)
        self.assertEqual(referral.referrer_user_id, referrer.id)

    async def test_self_referral_ignored(self):
        await self.feed_text("/start")
        async with self.factory() as s:
            me = await UserRepo(s).get_by_telegram_id(USER_ID)
        await self.feed_text(f"/start ref_{me.id}")
        async with self.factory() as s:
            self.assertIsNone(await ReferralRepo(s).get_by_referred(me.id))


class TestReferralReward(E2EBase):
    """Первая оплата приглашённого → +10 дней пригласившему, один раз."""

    def _notification(self, order_num, payment_num="1", date="2026-09-07T12:00:00+03:00"):
        return {
            "date": date,
            "order_id": f"p-{order_num}-{payment_num}",
            "order_num": order_num,
            "sum": "199.00",
            "customer_phone": "79990000001",
            "payment_status": "success",
            "subscription": {"id": "7", "active_manager": "1", "active_user": "1",
                             "payment_num": payment_num, "date_next_payment": "2026-10-07 12:00:00"},
        }

    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.factory() as s:
            self.referrer = await UserRepo(s).get_or_create(telegram_id=1001)
            self.friend = await UserRepo(s).get_or_create(telegram_id=1002)
            await ReferralRepo(s).attach(self.referrer.id, self.friend.id)
            await PaymentIntentRepo(s).create(self.friend.id, "f-1")
            await s.commit()

    async def test_referrer_without_subscription_gets_bonus_days(self):
        async with self.factory() as s:
            result = await service.apply_notification(s, self._notification("f-1"))
            await s.commit()
        self.assertEqual(result.outcome, service.OUTCOME_ACTIVATED)
        reward = result.referral_reward
        self.assertIsNotNone(reward)
        self.assertEqual(reward.telegram_id, 1001)
        self.assertIsNone(reward.shift_to)  # автопродления нет — переносить нечего
        async with self.factory() as s:
            self.assertTrue(await SubscriptionRepo(s).is_active(self.referrer.id))
            sub = await SubscriptionRepo(s).get(self.referrer.id)
            left = sub.expires_at - _now()
            self.assertTrue(timedelta(days=9, hours=23) < left <= timedelta(days=10))
            self.assertEqual((await ReferralRepo(s).stats(self.referrer.id))["paid"], 1)

    async def test_bonus_once_and_not_for_renewal(self):
        async with self.factory() as s:
            await service.apply_notification(s, self._notification("f-1"))
            await s.commit()
        async with self.factory() as s:
            renewal = await service.apply_notification(
                s, self._notification("f-1", payment_num="2", date="2026-10-07T12:00:00+03:00")
            )
            await s.commit()
        self.assertIsNone(renewal.referral_reward)

    async def test_recurring_referrer_gets_payment_date_shift(self):
        next_payment = _now() + timedelta(days=20)
        async with self.factory() as s:
            await SubscriptionRepo(s).apply_prodamus_payment(
                self.referrer.id,
                expires_at=next_payment + timedelta(days=2),
                next_payment_at=next_payment,
                customer_phone="79991112233",
            )
            await s.commit()
        async with self.factory() as s:
            result = await service.apply_notification(s, self._notification("f-1"))
            await s.commit()
        reward = result.referral_reward
        self.assertEqual(reward.shift_phone, "79991112233")
        self.assertEqual(reward.shift_to, next_payment + timedelta(days=10))
        self.assertEqual(reward.expires_at, next_payment + timedelta(days=12))

    async def test_renewal_does_not_cut_bonus_days(self):
        # Если перенос даты в Prodamus не удался, продление не должно «съесть» бонус.
        far = datetime(2027, 1, 1)
        async with self.factory() as s:
            await SubscriptionRepo(s).apply_prodamus_payment(self.friend.id, expires_at=far)
            await s.commit()
        async with self.factory() as s:
            result = await service.apply_notification(s, self._notification("f-1", payment_num="3"))
            await s.commit()
        self.assertEqual(result.expires_at, far)


class TestReferralRewardPostCommit(E2EBase):
    async def test_shift_saved_and_referrer_notified(self):
        from src.payments import webhook

        next_payment = datetime(2026, 10, 7, 9, 0)
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=1001)
            await SubscriptionRepo(s).apply_prodamus_payment(
                u.id, expires_at=next_payment, next_payment_at=next_payment, customer_phone="79991112233"
            )
            await s.commit()
        reward = service.ReferralReward(
            user_id=u.id, telegram_id=1001, days=10, expires_at=next_payment + timedelta(days=10),
            shift_phone="79991112233", shift_to=next_payment + timedelta(days=10),
        )
        set_date = AsyncMock(return_value={"ok": True})
        with patch("src.payments.webhook.prodamus.set_payment_date", set_date), \
             patch("src.payments.webhook.async_session_factory", self.factory):
            await webhook._apply_referral_reward(self.bot, reward)

        set_date.assert_awaited_once()
        self.assertEqual(set_date.await_args.kwargs["payment_date"], next_payment + timedelta(days=10))
        async with self.factory() as s:
            sub = await SubscriptionRepo(s).get(u.id)
            self.assertEqual(sub.next_payment_at, next_payment + timedelta(days=10))
        self.assertTrue(any("+10 дней" in t for t in self.session.texts()))

    def test_set_payment_date_payload(self):
        from src.payments import prodamus

        captured = {}

        async def fake_call(method, data):
            captured.update(method=method, **data)
            return {"ok": True}

        import asyncio
        with patch("src.payments.prodamus._rest_call", fake_call):
            asyncio.run(prodamus.set_payment_date(customer_phone="79991112233",
                                                  payment_date=datetime(2026, 10, 17, 9, 0)))
        self.assertEqual(captured["method"], "setSubscriptionPaymentDate")
        self.assertEqual(captured["auth_type"], "customer_phone")
        self.assertEqual(captured["customer_phone"], "+79991112233")
        self.assertEqual(captured["date"], "2026-10-17 12:00")  # UTC → МСК


if __name__ == "__main__":
    unittest.main()
