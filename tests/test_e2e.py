"""
End-to-end тесты: реальные Telegram-апдейты прогоняются через aiogram Dispatcher
с фейковой сессией бота (записывает API-вызовы) и временной файловой БД.
Проверяет весь конвейр: middleware, инъекцию репозиториев, FSM, callbacks, gating.
"""
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.db.base import Base  # noqa: E402
from src.db.middleware import DbSessionMiddleware  # noqa: E402
from src.db.models import PaymentIntent  # noqa: E402
from src.db.repositories import (  # noqa: E402
    PersonRepo,
    SearchHistoryRepo,
    SubscriptionRepo,
    UserRepo,
)
from src import admin_mode  # noqa: E402
from src.handlers import admin, cabinet, calculation, combinations, common, report, subscription  # noqa: E402

USER_ID = 555
ADMIN_ID = 555  # тот же пользователь — админ (для /grant самому себе)


class FakeSession(BaseSession):
    """Записывает все исходящие методы API и возвращает правдоподобные ответы."""

    def __init__(self):
        super().__init__()
        self.requests = []
        self._mid = 1000

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=1, is_bot=True, first_name="bot", username="numbot")
        if name in ("SendMessage", "SendDocument", "EditMessageText", "SendPhoto"):
            self._mid += 1
            return Message(
                message_id=self._mid,
                date=datetime.now(),
                chat=Chat(id=USER_ID, type="private"),
            ).as_(bot)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - не используется
        yield b""

    async def close(self):
        pass

    # --- удобные выборки для ассертов ---
    def names(self):
        return [type(m).__name__ for m in self.requests]

    def last_text(self):
        for m in reversed(self.requests):
            if type(m).__name__ in ("SendMessage", "EditMessageText"):
                return getattr(m, "text", "")
        return ""

    def texts(self):
        return [getattr(m, "text", "") for m in self.requests
                if type(m).__name__ in ("SendMessage", "EditMessageText")]

    def clear(self):
        self.requests.clear()


class E2EBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self._tmp.name}")
        async with self.engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.commit()
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

        # Подменяем фабрику сессий в middleware на временную БД.
        self._patch_factory = patch("src.db.middleware.async_session_factory", self.factory)
        self._patch_factory.start()
        # Делаем тестового пользователя админом для /grant.
        self._patch_admin = patch("src.admin_mode.ADMIN_USER_IDS", {ADMIN_ID})
        self._patch_admin.start()

        self.session = FakeSession()
        self.bot = Bot(token="123456:TESTTOKEN",
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                       session=self.session)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.update.middleware(DbSessionMiddleware())
        # Роутеры — модульные синглтоны; сбрасываем привязку к прошлому Dispatcher.
        admin_mode.reset_all()
        for m in (common, admin, subscription, cabinet, calculation, combinations, report):
            m.router._parent_router = None
        for m in (common, admin, subscription, cabinet, calculation, combinations, report):
            self.dp.include_router(m.router)

        self.user = User(id=USER_ID, is_bot=False, first_name="Тест", username="tester")
        self.chat = Chat(id=USER_ID, type="private")
        self._uid = 0

    async def asyncTearDown(self):
        await self.bot.session.close()
        await self.engine.dispose()
        self._patch_factory.stop()
        self._patch_admin.stop()
        admin_mode.reset_all()
        os.unlink(self._tmp.name)

    def _next_update_id(self):
        self._uid += 1
        return self._uid

    async def feed_text(self, text):
        msg = Message(message_id=self._next_update_id(), date=datetime.now(),
                      chat=self.chat, from_user=self.user, text=text).as_(self.bot)
        await self.dp.feed_update(self.bot, Update(update_id=self._next_update_id(), message=msg))

    async def feed_callback(self, data):
        carrier = Message(message_id=900, date=datetime.now(), chat=self.chat,
                          from_user=User(id=1, is_bot=True, first_name="bot")).as_(self.bot)
        cb = CallbackQuery(id=str(self._next_update_id()), from_user=self.user,
                           chat_instance="ci", message=carrier, data=data).as_(self.bot)
        await self.dp.feed_update(self.bot, Update(update_id=self._next_update_id(), callback_query=cb))


class TestHappyPath(E2EBase):
    async def test_start(self):
        await self.feed_text("/start")
        self.assertIn("SendMessage", self.session.names())
        self.assertIn("Привет", self.session.last_text())

    async def test_date_then_sector_and_free_quality(self):
        await self.feed_text("18.08.1984")
        self.assertIn("Результаты расчетов", self.session.last_text())
        self.assertIn("ДЕНЬГИ/ТРУД", self.session.last_text())

        # История поиска записалась в БД.
        async with self.factory() as s:
            from src.db.repositories import UserRepo
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
            history = await SearchHistoryRepo(s).list(u.id)
        self.assertEqual(len(history), 1)

        # Сектор (бесплатно) — показывает интерпретацию.
        self.session.clear()
        await self.feed_callback("sec:character:18.08.1984")
        self.assertIn("ХАРАКТЕР", self.session.last_text())

        # Бесплатное качество «Цель» — без paywall.
        self.session.clear()
        await self.feed_callback("qual:purpose:18.08.1984")
        self.assertIn("ЦЕЛЕУСТРЕМЛЕННОСТЬ", self.session.last_text())


class TestGating(E2EBase):
    async def test_paid_features_blocked_then_granted(self):
        await self.feed_text("18.08.1984")

        # Платное качество без премиума → paywall.
        self.session.clear()
        await self.feed_callback("qual:life:18.08.1984")
        self.assertIn("AnswerCallbackQuery", self.session.names())
        self.assertTrue(any("подписк" in t.lower() for t in self.session.texts()))

        # Комбинации без премиума → paywall.
        self.session.clear()
        await self.feed_callback("cmb:18.08.1984")
        self.assertTrue(any("подписк" in t.lower() for t in self.session.texts()))

        # Отчёт без премиума → paywall, документа нет.
        self.session.clear()
        await self.feed_callback("rep:18.08.1984")
        self.assertNotIn("SendDocument", self.session.names())

        # Выдаём премиум самому себе через /grant.
        self.session.clear()
        await self.feed_text(f"/grant {USER_ID}")
        self.assertTrue(any("Премиум выдан" in t for t in self.session.texts()))

        # Теперь отчёт приходит текстом + файлом .md.
        self.session.clear()
        await self.feed_callback("rep:18.08.1984")
        names = self.session.names()
        self.assertIn("SendDocument", names)
        doc = next(m for m in self.session.requests if type(m).__name__ == "SendDocument")
        self.assertTrue(doc.document.filename.endswith(".md"))

        # И комбинации теперь доступны.
        self.session.clear()
        await self.feed_callback("cmb:18.08.1984")
        self.assertTrue(any("Комбинации" in t for t in self.session.texts()))


class TestCabinetFSM(E2EBase):
    async def test_add_person_flow_and_open(self):
        # Запускаем FSM добавления через кнопку кабинета.
        await self.feed_callback("cab:add")
        await self.feed_text("09.05.1991")          # дата
        await self.feed_text("Иван")                # имя
        await self.feed_callback("add:skip")        # ФИО пропускаем

        # Человек сохранён в БД.
        async with self.factory() as s:
            from src.db.repositories import UserRepo
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
            people = await PersonRepo(s).list(u.id)
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].display_name, "Иван")
        self.assertEqual(people[0].birth_date.strftime("%d.%m.%Y"), "09.05.1991")
        self.assertIsNotNone(people[0].calc_snapshot)
        person_id = people[0].id

        # Открываем сохранённого человека — показывается экран результатов.
        self.session.clear()
        await self.feed_callback(f"pers:{person_id}")
        self.assertTrue(any("Результаты расчетов" in t for t in self.session.texts()))

    async def test_save_from_result(self):
        await self.feed_text("01.01.2000")
        self.session.clear()
        # Кнопка «Сохранить человека» → FSM с уже известной датой.
        await self.feed_callback("save:01.01.2000")
        await self.feed_callback("add:skip")  # имя пропускаем
        await self.feed_callback("add:skip")  # ФИО пропускаем

        async with self.factory() as s:
            from src.db.repositories import UserRepo
            u = await UserRepo(s).get_by_telegram_id(USER_ID)
            people = await PersonRepo(s).list(u.id)
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].birth_date.strftime("%d.%m.%Y"), "01.01.2000")


class TestSubscriptionFlow(E2EBase):
    """/subscribe больше не выдаёт премиум бесплатно — доступ только после оплаты."""

    async def _is_premium(self) -> bool:
        async with self.factory() as session:
            user = await UserRepo(session).get_or_create(telegram_id=USER_ID)
            return await SubscriptionRepo(session).is_active(user.id)

    async def test_subscribe_does_not_grant_premium(self):
        with patch("src.handlers.subscription.PAYMENTS_ENABLED", False):
            await self.feed_text("/subscribe")
        self.assertFalse(await self._is_premium())
        self.assertIn("недоступна", self.session.last_text())

    async def test_subscribe_sends_payment_button_and_creates_intent(self):
        link = "https://biohimrefresh.payform.ru/?order_id=x&signature=y"
        with patch("src.handlers.subscription.PAYMENTS_ENABLED", True), \
             patch("src.handlers.subscription.build_payment_link", return_value=link):
            await self.feed_text("/subscribe")

        message = self.session.requests[-1]
        button = message.reply_markup.inline_keyboard[0][0]
        self.assertEqual(button.url, link)
        self.assertFalse(await self._is_premium())

        async with self.factory() as session:
            user = await UserRepo(session).get_or_create(telegram_id=USER_ID)
            result = await session.execute(
                select(PaymentIntent).where(PaymentIntent.user_id == user.id)
            )
            intents = list(result.scalars().all())
        self.assertEqual(len(intents), 1)

    async def test_subscribe_shows_status_when_active(self):
        async with self.factory() as session:
            user = await UserRepo(session).get_or_create(telegram_id=USER_ID)
            await SubscriptionRepo(session).set_premium(user.id, is_premium=True, days=30)
            await session.commit()

        with patch("src.handlers.subscription.PAYMENTS_ENABLED", True):
            await self.feed_text("/subscribe")
        self.assertIn("Подписка активна", self.session.last_text())

    async def test_unsubscribe_without_recurring(self):
        await self.feed_text("/unsubscribe")
        self.assertIn("нет активной подписки", self.session.last_text())
