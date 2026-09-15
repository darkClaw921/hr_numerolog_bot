"""
Мини-миграции для SQLite: alembic в проекте нет, а `create_all` создаёт только
отсутствующие таблицы и не добавляет колонки в уже существующие.

Все изменения строго аддитивные и nullable — БД общая с будущим ботом
совместимости, старый код продолжает работать с новой схемой.
"""
import logging

logger = logging.getLogger(__name__)

# Колонки, появившиеся вместе с интеграцией Prodamus.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "subscriptions": {
        "provider": "VARCHAR(32)",
        "prodamus_subscription_id": "VARCHAR(64)",
        "prodamus_customer_phone": "VARCHAR(32)",
        "prodamus_customer_email": "VARCHAR(255)",
        "prodamus_active": "BOOLEAN",
        "next_payment_at": "DATETIME",
        "last_payment_at": "DATETIME",
        "cancelled_at": "DATETIME",
    },
}


async def ensure_schema(conn) -> None:
    """Идемпотентно добавляет недостающие колонки (вызывается после create_all)."""
    for table, columns in _ADDED_COLUMNS.items():
        await _add_missing_columns(conn, table, columns)


async def _add_missing_columns(conn, table: str, columns: dict[str, str]) -> None:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    rows = result.fetchall()
    if not rows:
        # Таблицы нет — её создаст create_all уже с нужными колонками.
        return
    existing = {row[1] for row in rows}
    for name, ddl in columns.items():
        if name in existing:
            continue
        # SQLite позволяет ADD COLUMN только для nullable-колонок или с константным DEFAULT.
        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        logger.info("Миграция: добавлена колонка %s.%s", table, name)
