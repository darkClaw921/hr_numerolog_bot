"""
Подписка: информация (/subscribe) и ручная выдача премиума админом (/grant).
Платёжная интеграция появится позже; пока премиум включается вручную.
"""
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.config import ADMIN_USER_IDS, SUBSCRIPTION_PRICE_RUB
from src.db.repositories import SubscriptionRepo, UserRepo

logger = logging.getLogger(__name__)
router = Router()

# Пока нет онлайн-оплаты — /subscribe выдаёт временный доступ на этот срок (дней).
TEMP_ACCESS_DAYS = 30


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, subscription_repo: SubscriptionRepo, db_user):
    """
    Информация о подписке. Пока платёжная интеграция не подключена — сразу выдаёт
    временный доступ к платным функциям с явной пометкой об этом.
    """
    await subscription_repo.set_premium(db_user.id, is_premium=True, days=TEMP_ACCESS_DAYS)
    await message.answer(
        f"💎 <b>Подписка — {SUBSCRIPTION_PRICE_RUB} ₽/мес</b>\n\n"
        "Открывает доступ к платным функциям:\n"
        "• 📄 Полный общий отчёт (текст + файл .md)\n"
        "• 🧩 Комбинации секторов\n"
        "• Коэффициенты: Быт, Темперамент, Семья, Стабильность, Трансформация\n\n"
        "⚠️ <b>Онлайн-оплата пока не подключена.</b>\n"
        f"✅ Доступ предоставлен временно (на {TEMP_ACCESS_DAYS} дней) — пользуйтесь бесплатно.\n\n"
        "<i>Когда подключим оплату, доступ будет продлеваться через неё.</i>",
        parse_mode="HTML",
    )


@router.message(Command("grant"))
async def cmd_grant(
    message: Message,
    command: CommandObject,
    user_repo: UserRepo,
    subscription_repo: SubscriptionRepo,
):
    """
    Ручная выдача премиума (только админ): /grant <telegram_id> [дней].
    Без указания дней — бессрочно.
    """
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.answer("⛔ Команда доступна только администраторам.")
        return

    args = (command.args or "").split()
    if not args:
        await message.answer("Использование: /grant &lt;telegram_id&gt; [дней]")
        return

    try:
        target_telegram_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else None
    except ValueError:
        await message.answer("❌ Неверные аргументы. Пример: /grant 123456789 30")
        return

    target_user = await user_repo.get_or_create(telegram_id=target_telegram_id)
    await subscription_repo.set_premium(target_user.id, is_premium=True, days=days)

    period = f"на {days} дн." if days else "бессрочно"
    await message.answer(f"✅ Премиум выдан пользователю {target_telegram_id} ({period}).")
