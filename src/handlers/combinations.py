"""
Хендлер комбинаций секторов (платная функция).
"""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.access import require_premium
from src.db.models import BotUser
from src.db.repositories import SubscriptionRepo
from src.formatting import format_combinations_block, send_long_message
from src.utils.combinations import get_matching_combinations
from src.utils.numerology import calculate_all

router = Router()


@router.callback_query(F.data.startswith("cmb:"))
async def handle_combinations(callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Показывает совпавшие комбинации (только для premium)."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    if not await require_premium(callback, "combinations", db_user, subscription_repo):
        return

    results = calculate_all(date_str)
    matches = get_matching_combinations(results)
    text = f"🧩 <b>Комбинации для {date_str}</b>\n\n{format_combinations_block(matches)}"
    await send_long_message(callback.message, text)
