"""
Основной поток расчёта: ввод даты, интерпретации секторов/качеств, навигация.

Экран результатов бывает двух видов: поиск по дате и профиль сохранённого человека
(id профиля приходит суффиксом callback_data, см. src/keyboards.py).
"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from src.access import is_premium, require_premium
from src.db.models import BotUser, Person
from src.db.repositories import PersonRepo, SearchHistoryRepo, SubscriptionRepo
from src.formatting import (
    edit_or_send,
    format_quality_interpretation,
    format_results_basic,
    format_sector_interpretation,
    person_label,
)
from src.keyboards import create_back_keyboard, create_result_keyboard, split_callback
from src.texts import QUALITY_ORDER, SECTOR_KEYS
from src.utils.interpretations import get_additional_qualities, get_all_interpretations
from src.utils.numerology import calculate_all, validate_results

logger = logging.getLogger(__name__)
router = Router()


def _date_to_obj(date_str: str):
    return datetime.strptime(date_str, "%d.%m.%Y").date()


async def resolve_person(
    person_repo: PersonRepo, db_user: BotUser, date_str: str, person_id: int | None
) -> Person | None:
    """
    Профиль, в контексте которого показывается экран: явно переданный id (только свой)
    либо уже сохранённый человек с этой датой — тогда «Сохранить» не предлагаем.
    """
    if person_id:
        person = await person_repo.get(person_id, db_user.id)
        if person is not None:
            return person
    return await person_repo.find_by_birth_date(db_user.id, _date_to_obj(date_str))


async def build_result_screen(
    date_str: str,
    db_user: BotUser,
    subscription_repo: SubscriptionRepo,
    person: Person | None = None,
):
    """Текст и клавиатура экрана результатов (профиля, если передан person)."""
    results = calculate_all(date_str)
    validate_results(results)
    premium = await is_premium(db_user, subscription_repo)
    label = person_label(person.display_name, person.full_name) if person else None
    text = format_results_basic(results, label)
    keyboard = create_result_keyboard(date_str, premium, person_id=person.id if person else None)
    return text, keyboard


@router.message(F.text.regexp(r"^\d{2}\.\d{2}\.\d{4}$"))
async def process_date(
    message: Message,
    subscription_repo: SubscriptionRepo,
    history_repo: SearchHistoryRepo,
    person_repo: PersonRepo,
    db_user: BotUser,
):
    """Обработчик даты рождения в формате DD.MM.YYYY."""
    date_str = message.text.strip()
    try:
        person = await resolve_person(person_repo, db_user, date_str, None)
        text, keyboard = await build_result_screen(date_str, db_user, subscription_repo, person)
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {e}")
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Ошибка расчёта для %s", date_str)
        await message.answer(f"❌ Произошла ошибка при расчетах: {e}")
        return
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    # Пишем историю поиска (не блокируя ответ при сбое БД).
    try:
        await history_repo.add(
            user_id=db_user.id,
            birth_date=_date_to_obj(date_str),
            person_id=person.id if person else None,
            raw_query=date_str,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось записать историю поиска")


@router.callback_query(F.data.startswith("sec:"))
async def handle_sector(callback: CallbackQuery):
    """Интерпретация сектора (бесплатно)."""
    (_, sector_key, date_str), person_id = split_callback(callback.data, 3)
    if sector_key not in SECTOR_KEYS:
        await callback.answer("Раздел недоступен", show_alert=True)
        return
    await callback.answer()
    try:
        results = calculate_all(date_str)
        interpretations = get_all_interpretations(results)
    except Exception:  # noqa: BLE001
        await callback.message.answer("❌ Не удалось получить интерпретацию.")
        return

    text = format_sector_interpretation(sector_key, interpretations[sector_key], date_str)
    await edit_or_send(callback, text, create_back_keyboard(date_str, person_id))


@router.callback_query(F.data.startswith("qual:"))
async def handle_quality(callback: CallbackQuery, subscription_repo: SubscriptionRepo, db_user: BotUser):
    """Интерпретация дополнительного качества (часть — платно)."""
    (_, quality_key, date_str), person_id = split_callback(callback.data, 3)
    back = create_back_keyboard(date_str, person_id)

    if quality_key not in QUALITY_ORDER:
        # Скрытый раздел (например, «Трансформация» со старой клавиатуры в истории чата).
        await callback.answer("Этот раздел временно недоступен", show_alert=True)
        return

    back_data = back.inline_keyboard[0][0].callback_data
    # require_premium сам отвечает на callback при отказе — повторный answer Telegram отклонит.
    if not await require_premium(callback, quality_key, db_user, subscription_repo, back_data=back_data):
        return
    await callback.answer()

    try:
        results = calculate_all(date_str)
        qualities = get_additional_qualities(results)
    except Exception:  # noqa: BLE001
        await callback.message.answer("❌ Не удалось получить интерпретацию.")
        return

    text = format_quality_interpretation(quality_key, qualities[quality_key], results)
    await edit_or_send(callback, text, back)


@router.callback_query(F.data.startswith("bk:"))
async def handle_back(
    callback: CallbackQuery,
    subscription_repo: SubscriptionRepo,
    person_repo: PersonRepo,
    db_user: BotUser,
):
    """Возврат к экрану результатов (или к профилю человека)."""
    await callback.answer()
    (_, date_str), person_id = split_callback(callback.data, 2)
    try:
        person = await resolve_person(person_repo, db_user, date_str, person_id)
        text, keyboard = await build_result_screen(date_str, db_user, subscription_repo, person)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось вернуться к результатам %s", date_str)
        await callback.message.answer("❌ Не удалось вернуться к результатам.")
        return
    await edit_or_send(callback, text, keyboard)


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    """Разделитель со старых клавиатур (из новых убран по ТЗ 06)."""
    await callback.answer()
