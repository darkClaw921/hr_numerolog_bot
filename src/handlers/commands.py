"""
Обработчики команд бота.
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from src.utils.numerology import calculate_all, parse_date
from src.utils.interpretations import get_all_interpretations, get_additional_qualities

# Максимальная длина сообщения в Telegram (4096 символов, оставляем запас)
MAX_MESSAGE_LENGTH = 4000

router = Router()


async def send_long_message(message: Message, text: str, parse_mode: str = "HTML"):
    """
    Отправляет длинное сообщение, разбивая его на части если необходимо.
    
    Args:
        message: Объект сообщения для ответа
        text: Текст для отправки
        parse_mode: Режим парсинга (HTML или None)
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        await message.answer(text, parse_mode=parse_mode)
        return
    
    # Разбиваем текст на части
    parts = []
    current_part = ""
    
    # Разбиваем по строкам, чтобы не разрывать HTML теги
    lines = text.split('\n')
    
    for line in lines:
        # Если добавление строки не превысит лимит
        if len(current_part) + len(line) + 1 <= MAX_MESSAGE_LENGTH:
            current_part += line + '\n'
        else:
            # Сохраняем текущую часть и начинаем новую
            if current_part:
                parts.append(current_part.strip())
            current_part = line + '\n'
    
    # Добавляем последнюю часть
    if current_part:
        parts.append(current_part.strip())
    
    # Отправляем все части
    for i, part in enumerate(parts):
        if i == 0:
            await message.answer(part, parse_mode=parse_mode)
        else:
            # Добавляем номер части для удобства
            await message.answer(f"<i>(продолжение {i + 1}/{len(parts)})</i>\n\n{part}", parse_mode=parse_mode)


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    await message.answer(
        "👋 Привет! Я бот для нумерологических расчетов по дате рождения.\n\n"
        "📅 Отправьте мне дату рождения в формате DD.MM.YYYY\n"
        "Например: 18.08.1984\n\n"
        "Используйте /help для получения справки."
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    await message.answer(
        "📖 Справка по использованию бота:\n\n"
        "Отправьте дату рождения в формате DD.MM.YYYY\n"
        "Например: 18.08.1984 или 05.12.1990\n\n"
        "Бот выполнит следующие расчеты:\n"
        "• Первое дополнительное число\n"
        "• Второе дополнительное число\n"
        "• Третье дополнительное число\n"
        "• Четвертое дополнительное число\n"
        "• Заполнение матрицы (секторы 1-9)\n"
        "• Сектор темперамент (3/5/7)\n"
        "• Сектор быт (4/5/6)\n"
        "• Сектор цель (1/4/7)\n"
        "• Сектор семья (2/5/8)\n"
        "• Число Судьбы\n\n"
        "Команды:\n"
        "/start - Начать работу\n"
        "/help - Показать эту справку"
    )


@router.message(F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def process_date(message: Message):
    """Обработчик даты рождения в формате DD.MM.YYYY."""
    date_str = message.text.strip()
    
    try:
        # Проверяем корректность даты
        parse_date(date_str)
        
        # Выполняем расчеты
        results = calculate_all(date_str)
        
        # Формируем основной ответ (без интерпретаций секторов)
        response = format_results_basic(results)
        await send_long_message(message, response, parse_mode="HTML")
        
        # Отправляем интерпретации секторов отдельными сообщениями
        interpretations = get_all_interpretations(results)
        await send_sector_interpretations(message, interpretations)
        
        # Получаем и отправляем дополнительные качества отдельным сообщением
        additional_qualities = get_additional_qualities(results)
        await send_additional_qualities(message, additional_qualities)
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при расчетах: {str(e)}")


async def send_sector_interpretations(message: Message, interpretations: dict):
    """
    Отправляет интерпретации секторов отдельными сообщениями.
    
    Args:
        message: Объект сообщения для ответа
        interpretations: Словарь с интерпретациями секторов
    """
    sector_names = {
        "character": "1. ХАРАКТЕР (Тип восприятия)",
        "energy": "2. ЭНЕРГИЯ",
        "interest": "3. ИНТЕРЕС",
        "health": "4. ЗДОРОВЬЕ",
        "logic": "5. ЛОГИКА",
        "labor": "6. ТРУД",
        "luck": "7. УДАЧА",
        "duty": "8. ДОЛГ",
        "memory": "9. ПАМЯТЬ"
    }
    
    await message.answer("📖 <b>ИНТЕРПРЕТАЦИИ СЕКТОРОВ:</b>", parse_mode="HTML")
    
    for key, name in sector_names.items():
        text = f"<b>{name}</b>\n{interpretations[key]}"
        await send_long_message(message, text, parse_mode="HTML")


async def send_additional_qualities(message: Message, qualities: dict):
    """
    Отправляет дополнительные качества отдельными сообщениями.
    
    Args:
        message: Объект сообщения для ответа
        qualities: Словарь с интерпретациями дополнительных качеств
    """
    await message.answer("📚 <b>ДОПОЛНИТЕЛЬНЫЕ КАЧЕСТВА:</b>", parse_mode="HTML")
    
    quality_names = {
        "life": "БЫТ",
        "temperament": "ПЛОТСКОЕ (Темперамент)",
        "family": "СЕМЬЯ",
        "stability": "СТАБИЛЬНОСТЬ",
        "purpose": "ЦЕЛЕУСТРЕМЛЕННОСТЬ",
        "transformation": "ТРАНСФОРМАЦИЯ",
        "destiny_number": "ЧИСЛО СУДЬБЫ (профессиональный вектор)"
    }
    
    for key, name in quality_names.items():
        text = f"<b>{name}</b>\n{qualities[key]}"
        await send_long_message(message, text, parse_mode="HTML")


def format_results_basic(results: dict) -> str:
    """
    Форматирует основные результаты расчетов без интерпретаций секторов.
    
    Args:
        results: Словарь с результатами расчетов
        
    Returns:
        Отформатированная строка с основными результатами
    """
    matrix = results["matrix"]
    
    # Формируем матрицу для отображения
    matrix_text = "📊 <b>Матрица (секторы 1-9):</b>\n"
    for sector in range(1, 10):
        numbers = matrix[sector]
        if numbers:
            count = len(numbers)
            numbers_str = " ".join(str(n) for n in numbers)
            matrix_text += f"Сектор {sector}: {numbers_str} (×{count})\n"
        else:
            matrix_text += f"Сектор {sector}: пусто\n"
    
    response = (
        f"🔮 <b>Результаты расчетов для {results['date']}</b>\n\n"
        f"📈 <b>Дополнительные числа:</b>\n"
        f"• Первое: {results['first_additional']}\n"
        f"• Второе: {results['second_additional']}\n"
        f"• Третье: {results['third_additional']}\n"
        f"• Четвертое: {results['fourth_additional']}\n\n"
        f"{matrix_text}\n"
        f"📊 <b>Коэффициенты секторов:</b>\n"
        f"• Темперамент (3/5/7): {results['sector_temperament']}\n"
        f"• Быт (4/5/6): {results['sector_life']}\n"
        f"• Цель (1/4/7): {results['sector_purpose']}\n"
        f"• Семья (2/5/8): {results['sector_family']}\n\n"
        f"⭐ <b>Число Судьбы:</b> {results['destiny_number']}"
    )
    
    return response


