"""
Режим проверки для админов: админ может временно «стать» обычным пользователем —
без подписки или с подпиской — и пройти все экраны так, как их видит клиент.

В режиме пользователя:
  * премиум-статус подменяется (реальная подписка и PREMIUM_USER_IDS игнорируются);
  * админ-команды (/grant, /payments) недоступны, как у обычного пользователя.
Переключатель — команда /admin, она работает в любом режиме.

Режим хранится в памяти процесса: после рестарта бот возвращается в режим админа
(безопасное значение по умолчанию, ничего не нужно «забыть выключить»).
"""
from src.config import ADMIN_USER_IDS

MODE_ADMIN = "admin"
MODE_FREE = "free"
MODE_PREMIUM = "premium"

MODE_TITLES = {
    MODE_ADMIN: "🛠 Админ",
    MODE_FREE: "👤 Пользователь без подписки",
    MODE_PREMIUM: "💎 Пользователь с подпиской",
}

_modes: dict[int, str] = {}


def is_admin_account(telegram_id: int) -> bool:
    """Аккаунт из ADMIN_USER_IDS — независимо от выбранного режима."""
    return telegram_id in ADMIN_USER_IDS


def get_mode(telegram_id: int) -> str:
    if not is_admin_account(telegram_id):
        return MODE_ADMIN
    return _modes.get(telegram_id, MODE_ADMIN)


def set_mode(telegram_id: int, mode: str) -> None:
    if mode not in MODE_TITLES:
        raise ValueError(f"Неизвестный режим: {mode}")
    if mode == MODE_ADMIN:
        _modes.pop(telegram_id, None)
    else:
        _modes[telegram_id] = mode


def has_admin_rights(telegram_id: int) -> bool:
    """Админ-права действуют, только если админ не переключился в режим пользователя."""
    return is_admin_account(telegram_id) and get_mode(telegram_id) == MODE_ADMIN


def simulated_premium(telegram_id: int) -> bool | None:
    """Подменённый премиум-статус в режиме пользователя; None — режим не включён."""
    mode = get_mode(telegram_id)
    if mode == MODE_FREE:
        return False
    if mode == MODE_PREMIUM:
        return True
    return None


def reset_all() -> None:
    """Сброс режимов (для тестов)."""
    _modes.clear()
