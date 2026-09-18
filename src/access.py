"""
Контроль доступа к платным функциям (gating).

Премиум-статус берётся из БД (таблица subscriptions) с fallback на список
PREMIUM_USER_IDS из конфига. Платёжной интеграции пока нет — премиум выдаётся
вручную (админ-команда /grant) или через PREMIUM_USER_IDS.
"""
from aiogram.types import CallbackQuery, Message

from src.admin_mode import simulated_premium
from src.config import PREMIUM_USER_IDS
from src.db.models import BotUser
from src.db.repositories import SubscriptionRepo
from src.texts import PAYWALL_ALERT, PAYWALL_TEXT

# Платные дополнительные качества (все коэффициенты-качества кроме «Цели»).
# «Трансформация» скрыта из интерфейса (ТЗ 06), но остаётся платной на случай возврата.
PREMIUM_QUALITY_KEYS = {"life", "temperament", "family", "stability", "transformation"}

# Бесплатные качества: Целеустремлённость и Число Судьбы.
FREE_QUALITY_KEYS = {"purpose", "destiny_number"}

# Полный набор платных фич (качества + отчёт + комбинации). Секторы 1-9 бесплатны.
PREMIUM_FEATURES = PREMIUM_QUALITY_KEYS | {"report", "combinations"}


def is_premium_feature(feature: str) -> bool:
    """True, если функция требует подписки."""
    return feature in PREMIUM_FEATURES


async def is_premium(db_user: BotUser, subscription_repo: SubscriptionRepo | None = None) -> bool:
    """
    Проверяет, активен ли премиум у пользователя.

    Сначала — режим проверки админа (src/admin_mode.py), затем список
    PREMIUM_USER_IDS (по telegram_id), затем БД (подписка по bot_users.id).
    """
    simulated = simulated_premium(db_user.telegram_id)
    if simulated is not None:
        return simulated
    if db_user.telegram_id in PREMIUM_USER_IDS:
        return True
    if subscription_repo is None:
        return False
    return await subscription_repo.is_active(db_user.id)


async def require_premium(
    event: Message | CallbackQuery,
    feature: str,
    db_user: BotUser,
    subscription_repo: SubscriptionRepo | None = None,
    back_data: str | None = None,
) -> bool:
    """
    Проверяет доступ к платной фиче. Если доступа нет — показывает paywall и
    возвращает False. Если фича бесплатна или есть премиум — возвращает True.
    back_data — callback кнопки «Назад» на пейволле (например, в профиль человека).
    """
    # Локальный импорт: keyboards сам импортирует access (is_premium_feature).
    from src.keyboards import paywall_keyboard

    if not is_premium_feature(feature):
        return True

    if await is_premium(db_user, subscription_repo):
        return True

    if isinstance(event, CallbackQuery):
        await event.answer(PAYWALL_ALERT, show_alert=True)
        if event.message is not None:
            await event.message.answer(PAYWALL_TEXT, parse_mode="HTML", reply_markup=paywall_keyboard(back_data))
    else:
        await event.answer(PAYWALL_TEXT, parse_mode="HTML", reply_markup=paywall_keyboard(back_data))
    return False
