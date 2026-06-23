"""
ORM-модели общей БД нумеролог-бота.

Главная сущность для будущего бота совместимости — `Person`: дата рождения
(источник истины) + опциональные имя/ФИО + денормализованный снапшот расчёта.
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

# Первичный ключ: на SQLite это INTEGER (алиас rowid с автоинкрементом); на других
# СУБД — BIGINT. AUTOINCREMENT в SQLite работает только с INTEGER PRIMARY KEY.
PkType = BigInteger().with_variant(Integer, "sqlite")


class BotUser(Base):
    """Пользователь Telegram. Таблица общая для обоих ботов (ключ — telegram_id)."""

    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    people: Mapped[list["Person"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    subscription: Mapped["Subscription | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Person(Base):
    """
    Сохранённый профиль человека.

    Самостоятельная сущность: бот совместимости берёт две строки `people`,
    читает их `birth_date` (+ опц. имя) и считает совместимость. `calc_snapshot`
    и `destiny_number` — денормализованный кэш для чтения без запуска расчёта.
    """

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="CASCADE"), nullable=False
    )
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)  # источник истины
    display_name: Mapped[str | None] = mapped_column(String(255))   # имя (опц.)
    full_name: Mapped[str | None] = mapped_column(String(512))      # ФИО (опц.)
    # Денормализованный кэш результата calculate_all (matrix + коэффициенты + ЧС).
    calc_snapshot: Mapped[dict | None] = mapped_column(JSON)
    calc_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    # ЧС вынесено отдельной колонкой для SQL-фильтрации без распаковки JSON.
    destiny_number: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["BotUser"] = relationship(back_populates="people")

    __table_args__ = (
        Index("ix_people_owner", "owner_user_id"),
        Index("ix_people_birth_date", "birth_date"),
        UniqueConstraint("owner_user_id", "birth_date", "full_name", name="uq_people_owner_birth_full"),
    )


class SearchHistory(Base):
    """История поисков пользователя (кого искал, списком)."""

    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="CASCADE"), nullable=False
    )
    # Если человек был сохранён — ссылка на профиль; иначе NULL (поиск «на лету»).
    person_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="SET NULL")
    )
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_query: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_search_history_user_created", "user_id", "created_at"),
    )


class Subscription(Base):
    """
    Текущий статус подписки пользователя (модель состояния, не журнал платежей).

    Платёжная интеграция появится позже; пока is_premium включается вручную
    (админ-команда /grant). Активность: is_premium AND (expires_at IS NULL OR expires_at > now).
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    price_rub: Mapped[int] = mapped_column(Integer, nullable=False, default=299)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["BotUser"] = relationship(back_populates="subscription")


class CompatibilityResult(Base):
    """
    Задел под будущий бот совместимости. Текущий бот эту таблицу не пишет —
    она кэширует результат совместимости пары `people` (контракт между ботами).
    """

    __tablename__ = "compatibility_results"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="SET NULL")
    )
    person_a_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    person_b_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    details: Mapped[dict | None] = mapped_column(JSON)
    calc_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("person_a_id <> person_b_id", name="distinct_people"),
        Index("ix_compat_pair", "person_a_id", "person_b_id"),
    )
