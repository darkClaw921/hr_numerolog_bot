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

    # --- Платёжный провайдер (Prodamus). Все поля nullable: у ручных выдач (/grant) их нет.
    provider: Mapped[str | None] = mapped_column(String(32))
    prodamus_subscription_id: Mapped[str | None] = mapped_column(String(64))
    prodamus_customer_phone: Mapped[str | None] = mapped_column(String(32))
    prodamus_customer_email: Mapped[str | None] = mapped_column(String(255))
    # Активна ли рекуррентка на стороне Prodamus. False + is_premium=True — оплаченный
    # период доживает, но продлений больше не будет.
    prodamus_active: Mapped[bool | None] = mapped_column(Boolean)
    next_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Реферальные дни, на которые не удалось сдвинуть автосписание в Prodamus: перенос
    # повторяется при следующем успешном списании, иначе дни «съест» оплаченный период.
    referral_bonus_pending_days: Mapped[int | None] = mapped_column(Integer)

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


class PaymentIntent(Base):
    """
    Намерение оплаты: связь выданного ботом order_id с пользователем.

    Уведомление Prodamus принимается только для order_id, который бот сам выдал —
    это защита от подделки идентификатора заказа.
    """

    __tablename__ = "payment_intents"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amount_rub: Mapped[float | None] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base):
    """
    Журнал платёжных событий Prodamus (не состояние подписки — состояние в `subscriptions`).

    `event_key` уникален и служит ключом идемпотентности: Prodamus повторяет доставку
    уведомления при таймауте, и повтор не должен продлевать подписку дважды.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    # NULL, если пользователя не удалось сопоставить — событие всё равно сохраняем для разбора.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="prodamus")
    event_key: Mapped[str] = mapped_column(String(191), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(64))
    order_num: Mapped[str | None] = mapped_column(String(64))
    amount_rub: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="rub")
    status: Mapped[str | None] = mapped_column(String(32))
    payment_type: Mapped[str | None] = mapped_column(String(64))
    # initial — первый платёж, renewal — автосписание, unknown — не удалось определить.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    subscription_payment_num: Mapped[int | None] = mapped_column(Integer)
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    customer_email: Mapped[str | None] = mapped_column(String(255))
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("event_key", name="uq_payments_event_key"),
        Index("ix_payments_user_created", "user_id", "created_at"),
        Index("ix_payments_order_id", "order_id"),
    )


class Referral(Base):
    """
    Приглашение по реферальной ссылке: кто кого привёл и выдан ли бонус.

    Один приглашённый — один реферер (unique). Бонус выдаётся один раз, при первом
    успешном платеже приглашённого; `rewarded_at` защищает от повторного начисления.
    """

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(PkType, primary_key=True, autoincrement=True)
    referrer_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="CASCADE"), nullable=False
    )
    referred_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bot_users.id", ondelete="CASCADE"), nullable=False
    )
    bonus_days: Mapped[int | None] = mapped_column(Integer)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_referrals_referred"),
        CheckConstraint("referrer_user_id <> referred_user_id", name="referral_not_self"),
        Index("ix_referrals_referrer", "referrer_user_id"),
    )
