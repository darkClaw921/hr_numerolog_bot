"""
aiogram-middleware: на каждый апдейт открывает сессию БД, прокидывает репозитории
в данные хендлеров и регистрирует пользователя Telegram (get_or_create).
"""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from src.db.repositories import (
    PaymentIntentRepo,
    PaymentRepo,
    PersonRepo,
    ReferralRepo,
    SearchHistoryRepo,
    SubscriptionRepo,
    UserRepo,
)
from src.db.session import async_session_factory


def _extract_user(event: TelegramObject):
    """Достаёт from_user из Update (поддерживаем message и callback_query)."""
    for attr in ("message", "edited_message", "callback_query", "inline_query"):
        obj = getattr(event, attr, None)
        from_user = getattr(obj, "from_user", None)
        if from_user is not None:
            return from_user
    return None


class DbSessionMiddleware(BaseMiddleware):
    """Сессия живёт один апдейт; commit при успехе, rollback при исключении."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            user_repo = UserRepo(session)
            data["session"] = session
            data["user_repo"] = user_repo
            data["person_repo"] = PersonRepo(session)
            data["history_repo"] = SearchHistoryRepo(session)
            data["subscription_repo"] = SubscriptionRepo(session)
            data["intent_repo"] = PaymentIntentRepo(session)
            data["payment_repo"] = PaymentRepo(session)
            data["referral_repo"] = ReferralRepo(session)

            tg_user = data.get("event_from_user")
            if tg_user is None and isinstance(event, Update):
                tg_user = _extract_user(event)
            if tg_user is not None and not tg_user.is_bot:
                data["db_user"] = await user_repo.get_or_create(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    last_name=tg_user.last_name,
                    language_code=tg_user.language_code,
                )
                # Коммитим регистрацию сразу: иначе write-блокировка SQLite
                # держится весь хендлер (включая ожидание ответов Telegram API),
                # и параллельные апдейты падают с "database is locked".
                await session.commit()

            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
