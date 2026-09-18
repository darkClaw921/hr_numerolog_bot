"""
Краевые ситуации доработок ТЗ 06: FSM-сохранение, мусорные callback_data, повторные
нажатия, реферальные ссылки, бонус при пробном периоде и сбое переноса списания.
"""
import os
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.methods import EditMessageText  # noqa: E402

from src.db.repositories import (  # noqa: E402
    PaymentIntentRepo,
    PersonRepo,
    ReferralRepo,
    SubscriptionRepo,
    UserRepo,
)
from src.formatting import edit_or_send  # noqa: E402
from src.handlers.cabinet import AddPerson  # noqa: E402
from src.payments import service, webhook  # noqa: E402
from tests.test_e2e import USER_ID, E2EBase  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EdgeBase(E2EBase):
    async def people(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            return await PersonRepo(s).list(u.id)

    async def fsm_state(self):
        from aiogram.fsm.storage.base import StorageKey

        key = StorageKey(bot_id=self.bot.id, chat_id=USER_ID, user_id=USER_ID)
        return await self.dp.storage.get_state(key)

    def answers(self):
        return [m for m in self.session.requests if type(m).__name__ == "AnswerCallbackQuery"]


class TestSaveFlowEdges(EdgeBase):
    async def test_cancel_command_during_name_does_not_save(self):
        await self.feed_callback("save:01.01.2000")
        await self.feed_text("/cancel")
        await self.feed_text("Иван")
        self.assertEqual(await self.people(), [])
        self.assertIsNone(await self.fsm_state())

    async def test_date_instead_of_name_is_not_saved_as_name(self):
        await self.feed_callback("save:01.01.2000")
        await self.feed_text("05.05.1995")
        self.assertIn("Похоже, это дата", self.session.last_text())
        self.assertEqual(await self.fsm_state(), AddPerson.waiting_name.state)
        await self.feed_callback("add:cancel")
        await self.feed_text("05.05.1995")  # после отмены — обычный расчёт
        self.assertIn("Результаты расчетов", self.session.last_text())

    async def test_unknown_command_during_name_not_saved(self):
        await self.feed_callback("save:01.01.2000")
        await self.feed_text("/foo")
        self.assertIn("идёт сохранение", self.session.last_text())
        self.assertEqual(await self.fsm_state(), AddPerson.waiting_name.state)

    async def test_menu_resets_fsm(self):
        await self.feed_callback("save:01.01.2000")
        await self.feed_text("/menu")
        self.assertIsNone(await self.fsm_state())

    async def test_long_name_truncated(self):
        await self.feed_callback("save:01.01.2000")
        await self.feed_text("Я" * 1000)
        await self.feed_text("Ф" * 1000)
        people = await self.people()
        self.assertEqual(len(people[0].display_name), 255)
        self.assertEqual(len(people[0].full_name), 512)
        self.session.clear()
        await self.feed_callback("cab:people")
        button = self.session.requests[-1].reply_markup.inline_keyboard[0][0]
        self.assertLess(len(button.text), 60)

    async def test_stale_save_button_opens_profile_instead_of_duplicate(self):
        await self.feed_callback("save:01.01.2000")
        await self.feed_callback("add:skip")
        await self.feed_callback("add:skip")
        self.session.clear()
        await self.feed_callback("save:01.01.2000")  # кнопка со старого экрана
        self.assertEqual(len(await self.people()), 1)
        self.assertIsNone(await self.fsm_state())
        self.assertIn("cab:people", str(self.session.requests[-1].reply_markup))

    async def test_stale_skip_button_answers(self):
        await self.feed_callback("add:skip")
        self.assertEqual(len(self.answers()), 1)
        self.assertTrue(self.answers()[0].show_alert)

    async def test_people_list_limited(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            for i in range(120):
                await PersonRepo(s).add(owner_user_id=u.id, birth_date=datetime(1990, 1, 1).date()
                                        + timedelta(days=i), display_name=f"P{i}")
            await s.commit()
        await self.feed_callback("cab:people")
        markup = self.session.requests[-1].reply_markup
        self.assertLessEqual(sum(len(r) for r in markup.inline_keyboard), 100)


class TestGarbageCallbacks(EdgeBase):
    async def test_unknown_sector_key(self):
        await self.feed_callback("sec:nope:18.08.1984")
        self.assertEqual(len(self.answers()), 1)
        self.assertNotIn("SendMessage", self.session.names())

    async def test_non_numeric_person(self):
        await self.feed_callback("pers:abc")
        self.assertIn("не найден", self.session.last_text())

    async def test_foreign_person_id(self):
        async with self.factory() as s:
            other = await UserRepo(s).get_or_create(telegram_id=4242)
            p = await PersonRepo(s).add(owner_user_id=other.id, birth_date=datetime(1990, 1, 1).date(),
                                        display_name="Чужой")
            await s.commit()
        await self.feed_callback(f"pers:{p.id}")
        self.assertNotIn("Чужой", " ".join(self.session.texts()))
        await self.feed_callback(f"bk:01.01.1990:{p.id}")
        self.assertNotIn("Чужой", " ".join(self.session.texts()))

    async def test_bad_save_date(self):
        await self.feed_callback("save:99.99.9999")
        self.assertTrue(self.answers()[0].show_alert)
        self.assertIsNone(await self.fsm_state())


class TestEditOrSend(unittest.IsolatedAsyncioTestCase):
    async def test_not_modified_does_not_duplicate(self):
        answer = AsyncMock()
        err = TelegramBadRequest(method=EditMessageText(text="x"), message="Bad Request: message is not modified")
        message = types.SimpleNamespace(edit_text=AsyncMock(side_effect=err), answer=answer)
        await edit_or_send(types.SimpleNamespace(message=message), "текст")
        answer.assert_not_awaited()

    async def test_document_message_falls_back_to_new_message(self):
        answer = AsyncMock()
        err = TelegramBadRequest(method=EditMessageText(text="x"), message="Bad Request: there is no text in the message to edit")
        message = types.SimpleNamespace(edit_text=AsyncMock(side_effect=err), answer=answer)
        await edit_or_send(types.SimpleNamespace(message=message), "текст")
        answer.assert_awaited_once()


class TestReferralLinkEdges(EdgeBase):
    async def test_huge_referral_id_does_not_break_start(self):
        await self.feed_text("/start ref_" + "9" * 40)
        self.assertIn("Привет", self.session.last_text())

    async def test_unknown_and_garbage_referrer(self):
        for payload in ("ref_424242", "ref_abc", "ref_", "other"):
            self.session.clear()
            await self.feed_text(f"/start {payload}")
            self.assertIn("Привет", self.session.last_text())

    async def test_second_link_does_not_rebind(self):
        async with self.factory() as s:
            a = await UserRepo(s).get_or_create(telegram_id=901)
            b = await UserRepo(s).get_or_create(telegram_id=902)
            await s.commit()
        await self.feed_text(f"/start ref_{a.id}")
        await self.feed_text(f"/start ref_{b.id}")
        async with self.factory() as s:
            me = await UserRepo(s).get_by_telegram_id(USER_ID)
            self.assertEqual((await ReferralRepo(s).get_by_referred(me.id)).referrer_user_id, a.id)

    async def test_existing_subscriber_not_attached(self):
        async with self.factory() as s:
            a = await UserRepo(s).get_or_create(telegram_id=901)
            me = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            await SubscriptionRepo(s).set_premium(me.id, days=5)
            await s.commit()
        await self.feed_text(f"/start ref_{a.id}")
        async with self.factory() as s:
            self.assertIsNone(await ReferralRepo(s).get_by_referred(me.id))

    async def test_attach_conflict_keeps_session_usable(self):
        async with self.factory() as s:
            a = await UserRepo(s).get_or_create(telegram_id=901)
            b = await UserRepo(s).get_or_create(telegram_id=902)
            me = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            await ReferralRepo(s).attach(a.id, me.id)
            await s.commit()
        async with self.factory() as s:
            me = await UserRepo(s).get_by_telegram_id(USER_ID)
            repo = ReferralRepo(s)
            # Гонка: проверка «уже привязан» прошла, а вставка упёрлась в уникальный индекс.
            with patch.object(repo, "get_by_referred", AsyncMock(return_value=None)):
                self.assertIsNone(await repo.attach(b.id, me.id))
            self.assertEqual(me.telegram_id, USER_ID)  # объекты сессии не «протухли»
            await s.commit()


class TestRewardEdges(EdgeBase):
    def _notification(self, order_num, payment_num="1", total="199.00", date="2026-09-07T12:00:00+03:00",
                      next_payment="2026-10-07 12:00:00"):
        return {
            "date": date, "order_id": f"p-{order_num}-{payment_num}-{date}", "order_num": order_num, "sum": total,
            "customer_phone": "79990000001", "payment_status": "success",
            "subscription": {"id": "7", "active_manager": "1", "active_user": "1",
                             "payment_num": payment_num, "date_next_payment": next_payment},
        }

    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.factory() as s:
            self.referrer = await UserRepo(s).get_or_create(telegram_id=1001)
            self.friend = await UserRepo(s).get_or_create(telegram_id=1002)
            await ReferralRepo(s).attach(self.referrer.id, self.friend.id)
            await PaymentIntentRepo(s).create(self.friend.id, "f-1")
            await PaymentIntentRepo(s).create(self.referrer.id, "r-1")
            await s.commit()

    async def _apply(self, data):
        async with self.factory() as s:
            result = await service.apply_notification(s, data)
            await s.commit()
        return result

    async def test_trial_zero_sum_gives_no_bonus(self):
        result = await self._apply(self._notification("f-1", total="0.00"))
        self.assertIsNone(result.referral_reward)
        async with self.factory() as s:
            self.assertIsNone((await ReferralRepo(s).get_by_referred(self.friend.id)).rewarded_at)

    async def test_stale_next_payment_not_shifted(self):
        async with self.factory() as s:
            await SubscriptionRepo(s).apply_prodamus_payment(
                self.referrer.id, expires_at=_now() - timedelta(days=5),
                next_payment_at=_now() - timedelta(days=30), customer_phone="79991112233")
            await s.commit()
        result = await self._apply(self._notification("f-1"))
        self.assertIsNone(result.referral_reward.shift_to)
        async with self.factory() as s:
            self.assertTrue(await SubscriptionRepo(s).is_active(self.referrer.id))

    async def test_lifetime_referrer(self):
        async with self.factory() as s:
            await SubscriptionRepo(s).set_premium(self.referrer.id, days=None)
            await s.commit()
        result = await self._apply(self._notification("f-1"))
        self.assertIsNone(result.referral_reward.expires_at)
        async with self.factory() as s:
            self.assertIsNone((await SubscriptionRepo(s).get(self.referrer.id)).expires_at)

    async def test_duplicate_delivery_rewards_once(self):
        data = self._notification("f-1")
        await self._apply(data)
        again = await self._apply(data)
        self.assertEqual(again.outcome, service.OUTCOME_DUPLICATE)
        async with self.factory() as s:
            self.assertEqual((await ReferralRepo(s).stats(self.referrer.id))["bonus_days"], 10)

    async def test_failed_shift_is_retried_on_next_charge(self):
        # У пригласившего идёт автопродление; перенос списания в Prodamus не удался.
        next_payment = _now() + timedelta(days=20)
        async with self.factory() as s:
            await SubscriptionRepo(s).apply_prodamus_payment(
                self.referrer.id, expires_at=next_payment + timedelta(days=2),
                next_payment_at=next_payment, customer_phone="79991112233")
            await s.commit()
        result = await self._apply(self._notification("f-1"))
        with patch("src.payments.webhook.prodamus.set_payment_date", AsyncMock(return_value={"ok": False})), \
             patch("src.payments.webhook.async_session_factory", self.factory):
            await webhook._apply_referral_reward(None, result.referral_reward)
        async with self.factory() as s:
            self.assertEqual((await SubscriptionRepo(s).get(self.referrer.id)).referral_bonus_pending_days, 10)

        # Следующее списание у пригласившего → повтор переноса на отложенные дни.
        new_next = (next_payment + timedelta(days=30)).replace(microsecond=0)
        msk = (new_next + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        renewal = await self._apply(self._notification("r-1", payment_num="2", next_payment=msk,
                                                       date="2026-10-01T12:00:00+03:00"))
        self.assertIsNotNone(renewal.pending_shift)
        self.assertEqual(renewal.pending_shift.shift_to, new_next + timedelta(days=10))
        ok = AsyncMock(return_value={"ok": True})
        with patch("src.payments.webhook.prodamus.set_payment_date", ok), \
             patch("src.payments.webhook.async_session_factory", self.factory):
            await webhook._apply_referral_reward(None, renewal.pending_shift)
        async with self.factory() as s:
            sub = await SubscriptionRepo(s).get(self.referrer.id)
            self.assertIsNone(sub.referral_bonus_pending_days)
            self.assertEqual(sub.next_payment_at, new_next + timedelta(days=10))
            self.assertGreaterEqual(sub.expires_at, new_next + timedelta(days=12))

    async def test_failed_retry_does_not_double_pending(self):
        reward = service.ReferralReward(user_id=self.referrer.id, telegram_id=None, days=10, expires_at=None,
                                        shift_phone="79991112233", shift_to=_now() + timedelta(days=40), retry=True)
        async with self.factory() as s:
            await SubscriptionRepo(s).apply_prodamus_payment(self.referrer.id, expires_at=_now() + timedelta(days=30))
            await SubscriptionRepo(s).add_pending_bonus(self.referrer.id, 10)
            await s.commit()
        with patch("src.payments.webhook.prodamus.set_payment_date", AsyncMock(return_value={"ok": False})), \
             patch("src.payments.webhook.async_session_factory", self.factory):
            await webhook._apply_referral_reward(None, reward)
        async with self.factory() as s:
            self.assertEqual((await SubscriptionRepo(s).get(self.referrer.id)).referral_bonus_pending_days, 10)


class TestSubscriptionScreenEdges(EdgeBase):
    async def test_overdue_next_payment_not_shown(self):
        async with self.factory() as s:
            u = await UserRepo(s).get_or_create(telegram_id=USER_ID)
            await SubscriptionRepo(s).apply_prodamus_payment(
                u.id, expires_at=_now() + timedelta(days=1), next_payment_at=_now() - timedelta(days=1))
            await s.commit()
        await self.feed_callback("cab:sub")
        past = (_now() - timedelta(days=1)).strftime("%d.%m.%Y")
        self.assertNotIn(past, self.session.last_text())


if __name__ == "__main__":
    unittest.main()
