"""
Полный общий отчёт (платная функция): единый текст + файл .md.
"""
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from src.access import require_premium
from src.db.models import BotUser
from src.db.repositories import SubscriptionRepo
from src.formatting import build_full_report, build_full_report_markdown, send_long_message
from src.utils.combinations import get_matching_combinations
from src.utils.numerology import calculate_all, validate_results

router = Router()


@router.callback_query(F.data.startswith("rep:"))
async def handle_report(
    callback: CallbackQuery,
    subscription_repo: SubscriptionRepo,
    db_user: BotUser,
):
    """Собирает полный отчёт и присылает его текстом и файлом .md (только premium)."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]

    if not await require_premium(callback, "report", db_user, subscription_repo):
        return

    results = calculate_all(date_str)
    validate_results(results)
    matches = get_matching_combinations(results)
    label = "Без имени"

    # Текст отчёта (с разбивкой по лимиту Telegram).
    html_report = build_full_report(results, label, matches)
    await send_long_message(callback.message, html_report)

    # Файл .md из памяти.
    md_report = build_full_report_markdown(results, label, matches)
    filename = f"report_{date_str.replace('.', '-')}.md"
    document = BufferedInputFile(md_report.encode("utf-8"), filename=filename)
    await callback.message.answer_document(document, caption="📄 Ваш полный отчёт")
