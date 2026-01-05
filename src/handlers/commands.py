"""
Обработчики команд бота.
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from src.utils.numerology import calculate_all, parse_date

router = Router()


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
        "• Сектор плотское (3/5/7)\n"
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
        
        # Формируем ответ
        response = format_results(results)
        
        await message.answer(response, parse_mode="HTML")
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при расчетах: {str(e)}")


def format_results(results: dict) -> str:
    """
    Форматирует результаты расчетов для вывода пользователю.
    
    Args:
        results: Словарь с результатами расчетов
        
    Returns:
        Отформатированная строка с результатами
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
        f"• Плотское (3/5/7): {results['sector_physical']}\n"
        f"• Быт (4/5/6): {results['sector_life']}\n"
        f"• Цель (1/4/7): {results['sector_purpose']}\n"
        f"• Семья (2/5/8): {results['sector_family']}\n\n"
        f"⭐ <b>Число Судьбы:</b> {results['destiny_number']}"
    )
    
    return response
