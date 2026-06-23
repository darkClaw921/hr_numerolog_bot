"""
Инициализация и запуск Telegram-бота.
"""
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import BOT_TOKEN
from src.db.middleware import DbSessionMiddleware
from src.db.session import init_models
from src.handlers import cabinet, calculation, combinations, common, report, subscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Основная функция для запуска бота."""
    # Инициализируем схему БД (создаёт таблицы, если их нет).
    await init_models()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware БД: сессия + репозитории + регистрация пользователя на каждый апдейт.
    dp.update.middleware(DbSessionMiddleware())

    # Порядок важен: cabinet (FSM-хендлеры) регистрируется до calculation,
    # чтобы во время ввода в FSM дата не перехватывалась общим обработчиком даты.
    dp.include_router(common.router)
    dp.include_router(subscription.router)
    dp.include_router(cabinet.router)
    dp.include_router(calculation.router)
    dp.include_router(combinations.router)
    dp.include_router(report.router)

    logger.info("Бот запущен")
    await dp.start_polling(bot)
