"""
Async-движок SQLAlchemy и фабрика сессий поверх SQLite.

Для общего доступа двух ботов к одному файлу БД включаем WAL (конкурентное
чтение + сериализованная запись) и принудительно включаем проверку внешних
ключей (в SQLite она по умолчанию выключена).
"""
import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import DATABASE_URL
from src.db.base import Base
# Импорт моделей обязателен: регистрирует таблицы в Base.metadata до create_all.
from src.db import models  # noqa: F401

logger = logging.getLogger(__name__)

# timeout=30: ждём снятия блокировки до 30с вместо 5с по умолчанию — записи
# конкурируют, когда несколько апдейтов обрабатываются одновременно.
engine = create_async_engine(DATABASE_URL, future=True, connect_args={"timeout": 30})


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Включает WAL и foreign_keys на каждое новое соединение SQLite."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


# expire_on_commit=False: объекты остаются доступны после commit (удобно в хендлерах).
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """Создаёт таблицы по моделям, если их ещё нет (вызывается при старте бота)."""
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()
    logger.info("Схема БД инициализирована (%s)", DATABASE_URL)
