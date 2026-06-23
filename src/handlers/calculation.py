"""
Основной поток расчёта: ввод даты, интерпретации секторов/качеств, навигация.
"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from src.access import is_premium, require_premium
from src.db.models import BotUser
from src.db.repositories import SearchHistoryRepo, SubscriptionRepo
from src.formatting import (
    format_quality_interpretation,
    format_results_basic,
    format_sector_interpretation,
)
from src.keyboards import create_back_keyboard, create_result_keyboard
from src.utils.interpretations import get_additional_qualities, get_all_interpretations
from src.utils.numerology import calculate_all, validate_results

logger = logging.getLogger(__name__)
router = Router()


def _date_to_obj(date_str: str):
    return datetime.strptime(date_str, "%d.%m.%Y").date()


async def render_result(
    target: Message,
    date_str: str,
    db_user: BotUser,
    subscription_repo: SubscriptionRepo,
    show_save: bool = True,
) -> Message:
    """Считает результаты по дате и отправляет базовый экран с клавиатурой."""
    results = calculate_all(date_str)
    validate_results(results)
    premium = await is_premium(db_user, subscription_repo)
    text = format_results_basic(results)
    keyboard = create_result_keyboard(date_str, premium, show_save=show_save)
    return await target.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(F.text.regexp(r"^\d{2}\.\d{2}\.\d{4}$"))
async def process_date(
    message: Message,
    subscription_repo: SubscriptionRepo,
    history_repo: SearchHistoryRepo,
    db_user: BotUser,
):
    """Обработчик даты рождения в формате DD.MM.YYYY."""
    date_str = message.text.strip()
    try:
        await render_result(message, date_str, db_user, subscription_repo, show_save=True)
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {e}")
        return
    except Exception as e:  # noqa: BLE001
        await message.answer(f"❌ Произошла ошибка при расчетах: {e}")
        return

    # Пишем историю поиска (не блокируя ответ при сбое БД).
    try:
        await history_repo.add(
            user_id=db_user.id,
            birth_date=_date_to_obj(date_str),
            person_id=None,
            raw_query=date_str,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось записать историю поиска")


@router.callback_query(F.data.startswith("sec:"))
async def handle_sector(callback: CallbackQuery):
    """Интерпретация сектора (бесплатно)."""
    await callback.answer()
    _, sector_key, date_str = callback.data.split(":")
    try:
        results = calculate_all(date_str)
        interpretations = get_all_interpretations(results)
    except Exception:  # noqa: BLE001
        await callback.message.answer("❌ Не удалось получить интерпретацию.")
        return

    text = format_sector_interpretation(sector_key, interpretations[sector_key], date_str)
    await _edit_or_send(callback, text, create_back_keyboard(date_str))


@router.callback_query(F.data.startswith("qual:"))
async def handle_quality(callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Интерпретация дополнительного качества (часть — платно)."""
    await callback.answer()
    _, quality_key, date_str = callback.data.split(":")

    if not await require_premium(callback, quality_key, db_user, subscription_repo):
        return

    try:
        results = calculate_all(date_str)
        qualities = get_additional_qualities(results)
    except Exception:  # noqa: BLE001
        await callback.message.answer("❌ Не удалось получить интерпретацию.")
        return

    text = format_quality_interpretation(quality_key, qualities[quality_key], date_str)
    await _edit_or_send(callback, text, create_back_keyboard(date_str))


@router.callback_query(F.data.startswith("bk:"))
async def handle_back(callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Возврат к основному экрану результатов."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    try:
        results = calculate_all(date_str)
        premium = await is_premium(db_user, subscription_repo)
        text = format_results_basic(results)
        keyboard = create_result_keyboard(date_str, premium, show_save=True)
    except Exception:  # noqa: BLE001
        await callback.message.answer("❌ Не удалось вернуться к результатам.")
        return
    await _edit_or_send(callback, text, keyboard)


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    """Неактивная кнопка-разделитель."""
    await callback.answer()


async def _edit_or_send(callback: CallbackQuery, text: str, keyboard):
    """Пытается отредактировать сообщение; если не вышло — отправляет новое."""
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:  # noqa: BLE001
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
