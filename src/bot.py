"""
Инициализация и запуск Telegram-бота.
"""
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from src.config import (
    BOT_TOKEN,
    PAYMENTS_ENABLED,
    PRODAMUS_WEBHOOK_HOST,
    PRODAMUS_WEBHOOK_PATH,
    PRODAMUS_WEBHOOK_PORT,
)
from src.db.middleware import DbSessionMiddleware
from src.db.session import init_models
from src.handlers import cabinet, calculation, combinations, common, report, subscription
from src.payments.webhook import create_webhook_app

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
        # 25с вместо 60с по умолчанию: сеть до api.telegram.org нестабильна,
        # зависший запрос должен падать быстро, чтобы повтор пользователя прошёл.
        session=AiohttpSession(timeout=25),
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

    # Приёмник уведомлений Prodamus живёт в этом же процессе рядом с polling.
    # AppRunner, а не web.run_app: последний заводит свой event loop и обработчики
    # сигналов, что конфликтует с asyncio.run в main.py.
    runner = None
    if PAYMENTS_ENABLED:
        runner = web.AppRunner(create_webhook_app(bot), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, PRODAMUS_WEBHOOK_HOST, PRODAMUS_WEBHOOK_PORT).start()
        logger.info(
            "Вебхук Prodamus слушает %s:%s%s",
            PRODAMUS_WEBHOOK_HOST,
            PRODAMUS_WEBHOOK_PORT,
            PRODAMUS_WEBHOOK_PATH,
        )

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        if runner is not None:
            await runner.cleanup()
