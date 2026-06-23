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

# Стоимость подписки в рублях (для текста-оффера).
SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "299"))
