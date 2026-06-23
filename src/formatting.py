"""
Форматирование сообщений и сборка полного отчёта.

Все блоки результата вынесены в отдельные функции, чтобы и базовый экран, и
полный отчёт собирались из одних и тех же кусков без дублирования.
"""
import html
import re
from typing import List, Tuple

from aiogram.types import Message

from src.texts import QUALITY_NAMES, QUALITY_ORDER, SECTOR_KEYS, SECTOR_NAMES
from src.utils.interpretations import get_additional_qualities, get_all_interpretations

# Максимальная длина сообщения в Telegram (4096), оставляем запас.
MAX_MESSAGE_LENGTH = 4000


async def send_long_message(message: Message, text: str, parse_mode: str = "HTML"):
    """Отправляет длинное сообщение, разбивая его на части по строкам если нужно."""
    if len(text) <= MAX_MESSAGE_LENGTH:
        await message.answer(text, parse_mode=parse_mode)
        return

    parts: List[str] = []
    current_part = ""
    for line in text.split("\n"):
        if len(current_part) + len(line) + 1 <= MAX_MESSAGE_LENGTH:
            current_part += line + "\n"
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + "\n"
    if current_part:
        parts.append(current_part.strip())

    for i, part in enumerate(parts):
        if i == 0:
            await message.answer(part, parse_mode=parse_mode)
        else:
            await message.answer(
                f"<i>(продолжение {i + 1}/{len(parts)})</i>\n\n{part}", parse_mode=parse_mode
            )


def _matrix_block(results: dict) -> str:
    matrix = results["matrix"]
    text = "📊 <b>Матрица (секторы 1-9):</b>\n"
    for sector in range(1, 10):
        numbers = matrix[sector]
        sector_name = SECTOR_NAMES[sector]
        if numbers:
            numbers_str = " ".join(str(n) for n in numbers)
            text += f"Сектор {sector} ({sector_name}): {numbers_str} (×{len(numbers)})\n"
        else:
            text += f"Сектор {sector} ({sector_name}): пусто\n"
    return text


def _coefficients_block(results: dict) -> str:
    return (
        "📊 <b>Коэффициенты секторов:</b>\n"
        f"• Темперамент (3/5/7): {results['sector_temperament']}\n"
        f"• Быт (4/5/6): {results['sector_life']}\n"
        f"• Цель (1/4/7): {results['sector_purpose']}\n"
        f"• Семья (2/5/8): {results['sector_family']}\n"
    )


def _destiny_block(results: dict) -> str:
    return f"⭐ <b>Число Судьбы:</b> {results['destiny_number']}\n"


def _additional_numbers_block(results: dict) -> str:
    return (
        "📈 <b>Дополнительные числа:</b>\n"
        f"• Первое: {results['first_additional']}\n"
        f"• Второе: {results['second_additional']}\n"
        f"• Третье: {results['third_additional']}\n"
        f"• Четвертое: {results['fourth_additional']}\n"
    )


def format_results_basic(results: dict) -> str:
    """
    Базовый экран результатов. По ТЗ блок «Дополнительные числа» перемещён вниз:
    матрица → коэффициенты → Число Судьбы → дополнительные числа.
    """
    return (
        f"🔮 <b>Результаты расчетов для {results['date']}</b>\n\n"
        f"{_matrix_block(results)}\n"
        f"{_coefficients_block(results)}\n"
        f"{_destiny_block(results)}\n"
        f"{_additional_numbers_block(results)}\n"
        "💡 <i>Нажмите на кнопку ниже, чтобы узнать интерпретацию сектора или "
        "дополнительного качества</i>"
    )


def format_sector_interpretation(sector_key: str, interpretation: str, date: str) -> str:
    sector_num = SECTOR_KEYS[sector_key]
    sector_name = SECTOR_NAMES[sector_num]
    return (
        f"🔮 <b>Результаты расчетов для {date}</b>\n\n"
        f"📖 <b>Сектор {sector_num} ({sector_name})</b>\n\n"
        f"{interpretation}"
    )


def format_quality_interpretation(quality_key: str, interpretation: str, date: str) -> str:
    quality_name = QUALITY_NAMES[quality_key]
    return (
        f"🔮 <b>Результаты расчетов для {date}</b>\n\n"
        f"📚 <b>{quality_name}</b>\n\n"
        f"{interpretation}"
    )


def format_combinations_block(matches: List[Tuple[str, str]]) -> str:
    """Группирует совпавшие комбинации по разделам в единый текст."""
    if not matches:
        return "По текущим коэффициентам подходящих комбинаций не выявлено."
    text = ""
    current_group = None
    for group, combo_text in matches:
        if group != current_group:
            text += f"\n<b>🔹 {group}</b>\n\n"
            current_group = group
        text += f"• {combo_text}\n\n"
    return text.strip()


def build_full_report(results: dict, person_label: str, matches: List[Tuple[str, str]]) -> str:
    """
    Собирает единый HTML-отчёт по человеку: все секторы, качества и комбинации.
    Порядок секций соблюдает ТЗ — дополнительные числа в самом низу.
    """
    parts: List[str] = [
        f"📄 <b>Полный отчёт — {person_label}</b>\n"
        f"<i>Дата рождения: {results['date']}</i>",
        _matrix_block(results),
        _coefficients_block(results),
        _destiny_block(results),
    ]

    # Секторы 1-9
    interpretations = get_all_interpretations(results)
    parts.append("━━━━━━━━━━━━━━━━\n📖 <b>СЕКТОРЫ МАТРИЦЫ</b>")
    for key, sector_num in SECTOR_KEYS.items():
        parts.append(f"<b>Сектор {sector_num} ({SECTOR_NAMES[sector_num]})</b>\n\n{interpretations[key]}")

    # Дополнительные качества
    qualities = get_additional_qualities(results)
    parts.append("━━━━━━━━━━━━━━━━\n📚 <b>ДОПОЛНИТЕЛЬНЫЕ КАЧЕСТВА</b>")
    for key in QUALITY_ORDER:
        parts.append(f"<b>{QUALITY_NAMES[key]}</b>\n\n{qualities[key]}")

    # Комбинации
    parts.append("━━━━━━━━━━━━━━━━\n🧩 <b>КОМБИНАЦИИ</b>")
    parts.append(format_combinations_block(matches))

    # Дополнительные числа — внизу (по ТЗ)
    parts.append("━━━━━━━━━━━━━━━━\n" + _additional_numbers_block(results))

    return "\n\n".join(parts)


def _html_to_markdown(text: str) -> str:
    """Конвертирует Telegram-HTML в чистый Markdown (для файла .md)."""
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<i>", "_").replace("</i>", "_")
    text = text.replace("<code>", "`").replace("</code>", "`")
    text = text.replace("<br>", "\n").replace("<br/>", "\n")
    # Удаляем все прочие теги
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    return html.unescape(text)


def build_full_report_markdown(results: dict, person_label: str, matches: List[Tuple[str, str]]) -> str:
    """Markdown-версия полного отчёта (из того же HTML-источника)."""
    return _html_to_markdown(build_full_report(results, person_label, matches))


def person_label(display_name: str | None, full_name: str | None) -> str:
    """Человекочитаемая метка человека: имя → ФИО → «Без имени»."""
    return display_name or full_name or "Без имени"
