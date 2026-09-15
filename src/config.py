"""
Модуль для загрузки конфигурации бота из переменных окружения.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения. Создайте файл .env с токеном бота.")

# Строка подключения к БД. По умолчанию — локальный файл SQLite.
# Оба бота (нумеролог и будущий бот совместимости) должны указывать на ОДИН файл.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./numerology.db")

# Список Telegram ID, которым премиум выдаётся без оплаты (fallback к БД).
PREMIUM_USER_IDS = {int(x) for x in os.getenv("PREMIUM_USER_IDS", "").split(",") if x.strip()}

# Список Telegram ID администраторов (могут выдавать премиум командой /grant).
ADMIN_USER_IDS = {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()}

# Стоимость подписки в рублях (для текста-оффера) — должна совпадать с `cost` подписки в Prodamus.
SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "299"))
# Цена первого платежа, если в подписке Prodamus задана скидка на первый платёж
# (first_payment_discount). По умолчанию скидки нет — первый платёж равен обычной цене.
# Пустое значение (как в .env.example) тоже означает «без скидки».
SUBSCRIPTION_FIRST_PAYMENT_RUB = int(os.getenv("SUBSCRIPTION_FIRST_PAYMENT_RUB") or SUBSCRIPTION_PRICE_RUB)


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- Платежи Prodamus ---------------------------------------------------------
# Пока выключено — бот работает как раньше, HTTP-сервер вебхука не поднимается.
PAYMENTS_ENABLED = _flag("PAYMENTS_ENABLED")

PRODAMUS_FORM_URL = os.getenv("PRODAMUS_FORM_URL", "https://biohimrefresh.payform.ru").rstrip("/")
PRODAMUS_SECRET_KEY = os.getenv("PRODAMUS_SECRET_KEY", "")
# ID клубной подписки из ЛК Prodamus.
PRODAMUS_SUBSCRIPTION_ID = os.getenv("PRODAMUS_SUBSCRIPTION_ID", "")
# Пробный период: первое списание откладывается на столько дней (0 — списание сразу).
PRODAMUS_TRIAL_DAYS = int(os.getenv("PRODAMUS_TRIAL_DAYS", "0"))
PRODAMUS_DEMO_MODE = _flag("PRODAMUS_DEMO_MODE")
# Запас после даты следующего списания, чтобы доступ не пропадал между попытками списания.
PRODAMUS_GRACE_DAYS = int(os.getenv("PRODAMUS_GRACE_DAYS", "2"))
PRODAMUS_SYS = os.getenv("PRODAMUS_SYS", "")

# Публичный HTTPS-адрес (reverse proxy) — из него собирается urlNotification.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
PRODAMUS_WEBHOOK_PATH = os.getenv("PRODAMUS_WEBHOOK_PATH", "/prodamus/webhook")
PRODAMUS_WEBHOOK_HOST = os.getenv("PRODAMUS_WEBHOOK_HOST", "0.0.0.0")
PRODAMUS_WEBHOOK_PORT = int(os.getenv("PRODAMUS_WEBHOOK_PORT", "8080"))

# Длительность оплаченного периода, если Prodamus не прислал date_next_payment.
SUBSCRIPTION_PERIOD_DAYS = int(os.getenv("SUBSCRIPTION_PERIOD_DAYS", "31"))
# Username бота без @ — на него ведут urlSuccess/urlReturn, чтобы вернуть пользователя в бот.
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")

if PAYMENTS_ENABLED:
    # Fail-fast: без этих значений ссылки на оплату будут молча битыми.
    _missing = [
        name
        for name, value in (
            ("PRODAMUS_SECRET_KEY", PRODAMUS_SECRET_KEY),
            ("PRODAMUS_SUBSCRIPTION_ID", PRODAMUS_SUBSCRIPTION_ID),
            ("PUBLIC_BASE_URL", PUBLIC_BASE_URL),
            ("BOT_USERNAME", BOT_USERNAME),
        )
        if not value
    ]
    if _missing:
        raise ValueError(
            "PAYMENTS_ENABLED=true, но не заданы: " + ", ".join(_missing) + ". "
            "Заполните их в .env или выключите PAYMENTS_ENABLED."
        )
    if not PUBLIC_BASE_URL.startswith("https://"):
        raise ValueError("PUBLIC_BASE_URL должен начинаться с https:// — Prodamus шлёт вебхук только по HTTPS.")
