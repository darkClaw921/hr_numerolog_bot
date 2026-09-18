"""
Хендлер комбинаций секторов (платная функция).
"""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.access import require_premium
from src.db.models import BotUser
from src.db.repositories import SubscriptionRepo
from src.formatting import edit_or_send, format_combinations_block
from src.keyboards import create_back_keyboard, split_callback
from src.utils.combinations import get_matching_combinations
from src.utils.numerology import calculate_all

router = Router()


@router.callback_query(F.data.startswith("cmb:"))
async def handle_combinations(callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Показывает совпавшие комбинации (только для premium) с кнопкой «Назад»."""
    (_, date_str), person_id = split_callback(callback.data, 2)
    back = create_back_keyboard(date_str, person_id)

    back_data = back.inline_keyboard[0][0].callback_data
    if not await require_premium(callback, "combinations", db_user, subscription_repo, back_data=back_data):
        return
    await callback.answer()

    results = calculate_all(date_str)
    matches = get_matching_combinations(results)
    text = f"🧩 <b>Комбинации для {date_str}</b>\n\n{format_combinations_block(matches)}"
    await edit_or_send(callback, text, back)
