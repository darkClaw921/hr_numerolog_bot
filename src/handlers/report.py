"""
Полный общий отчёт (платная функция): единый текст + файл .md.
"""
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from src.access import require_premium
from src.db.models import BotUser
from src.db.repositories import PersonRepo, SubscriptionRepo
from src.formatting import build_full_report, build_full_report_markdown, person_label, send_long_message
from src.keyboards import create_back_keyboard, split_callback
from src.utils.combinations import get_matching_combinations
from src.utils.numerology import calculate_all, validate_results

router = Router()


@router.callback_query(F.data.startswith("rep:"))
async def handle_report(
    callback: CallbackQuery,
    subscription_repo: SubscriptionRepo,
    person_repo: PersonRepo,
    db_user: BotUser,
):
    """Собирает полный отчёт и присылает его текстом и файлом .md (только premium)."""
    (_, date_str), person_id = split_callback(callback.data, 2)
    back = create_back_keyboard(date_str, person_id)

    back_data = back.inline_keyboard[0][0].callback_data
    if not await require_premium(callback, "report", db_user, subscription_repo, back_data=back_data):
        return
    await callback.answer()

    results = calculate_all(date_str)
    validate_results(results)
    matches = get_matching_combinations(results)
    person = await person_repo.get(person_id, db_user.id) if person_id else None
    label = person_label(person.display_name, person.full_name) if person else "Без имени"

    # Текст отчёта (с разбивкой по лимиту Telegram).
    html_report = build_full_report(results, label, matches)
    await send_long_message(callback.message, html_report)

    # Файл .md из памяти; «Назад» — под файлом, последним сообщением отчёта.
    md_report = build_full_report_markdown(results, label, matches)
    filename = f"report_{date_str.replace('.', '-')}.md"
    document = BufferedInputFile(md_report.encode("utf-8"), filename=filename)
    await callback.message.answer_document(document, caption="📄 Ваш полный отчёт", reply_markup=back)
