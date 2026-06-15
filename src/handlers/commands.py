"""
Обработчики команд бота.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from src.utils.numerology import calculate_all, parse_date
from src.utils.interpretations import get_all_interpretations, get_additional_qualities
from src.utils.combinations import get_matching_combinations

# Максимальная длина сообщения в Telegram (4096 символов, оставляем запас)
MAX_MESSAGE_LENGTH = 4000

router = Router()

# Глобальный словарь для хранения результатов расчетов по message_id
_results_cache = {}

# Словари с названиями секторов и дополнительных качеств
SECTOR_NAMES = {
    1: "ХАРАКТЕР (Тип восприятия)",
    2: "ЭНЕРГИЯ",
    3: "ИНТЕРЕС",
    4: "ЗДОРОВЬЕ",
    5: "ЛОГИКА",
    6: "ТРУД",
    7: "УДАЧА",
    8: "ДОЛГ",
    9: "ПАМЯТЬ"
}

SECTOR_KEYS = {
    "character": 1,
    "energy": 2,
    "interest": 3,
    "health": 4,
    "logic": 5,
    "labor": 6,
    "luck": 7,
    "duty": 8,
    "memory": 9
}

QUALITY_NAMES = {
    "life": "БЫТ",
    "temperament": "ПЛОТСКОЕ (Темперамент)",
    "family": "СЕМЬЯ",
    "stability": "СТАБИЛЬНОСТЬ",
    "purpose": "ЦЕЛЕУСТРЕМЛЕННОСТЬ",
    "transformation": "ТРАНСФОРМАЦИЯ",
    "destiny_number": "ЧИСЛО СУДЬБЫ (профессиональный вектор)"
}


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


def create_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Создает inline клавиатуру с кнопками для всех секторов и дополнительных качеств.
    
    Returns:
        InlineKeyboardMarkup с кнопками
    """
    buttons = []
    
    # Кнопки для секторов 1-9 (по 3 в ряд)
    sector_row = []
    for sector_num, sector_name in SECTOR_NAMES.items():
        key = [k for k, v in SECTOR_KEYS.items() if v == sector_num][0]
        sector_row.append(InlineKeyboardButton(
            text=f"{sector_num}",
            callback_data=f"sector:{key}"
        ))
        if len(sector_row) == 3:
            buttons.append(sector_row)
            sector_row = []
    if sector_row:
        buttons.append(sector_row)
    
    # Разделитель
    buttons.append([InlineKeyboardButton(
        text="━━━━━━━━━━━━━━━━",
        callback_data="noop"
    )])
    
    # Кнопки для дополнительных качеств (по 2 в ряд)
    quality_row = []
    quality_order = ["life", "temperament", "family", "stability", "purpose", "transformation", "destiny_number"]
    for key in quality_order:
        quality_row.append(InlineKeyboardButton(
            text=QUALITY_NAMES[key].split()[0],  # Берем первое слово для краткости
            callback_data=f"quality:{key}"
        ))
        if len(quality_row) == 2:
            buttons.append(quality_row)
            quality_row = []
    if quality_row:
        buttons.append(quality_row)

    # Отдельная кнопка для комбинаций секторов
    buttons.append([InlineKeyboardButton(
        text="🧩 Комбинации",
        callback_data="combos:show"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
        
        # Создаем inline клавиатуру
        keyboard = create_inline_keyboard()
        
        # Отправляем сообщение с кнопками
        sent_message = await message.answer(response, parse_mode="HTML", reply_markup=keyboard)
        
        # Сохраняем результаты расчетов в глобальном словаре по message_id
        _results_cache[sent_message.message_id] = {
            'results': results,
            'date': date_str
        }
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при расчетах: {str(e)}")


def format_sector_interpretation(sector_key: str, interpretation: str, date: str) -> str:
    """
    Форматирует интерпретацию сектора для отображения.
    
    Args:
        sector_key: Ключ сектора (character, energy, и т.д.)
        interpretation: Текст интерпретации
        date: Дата рождения
        
    Returns:
        Отформатированная строка
    """
    sector_num = SECTOR_KEYS[sector_key]
    sector_name = SECTOR_NAMES[sector_num]
    
    return (
        f"🔮 <b>Результаты расчетов для {date}</b>\n\n"
        f"📖 <b>Сектор {sector_num} ({sector_name})</b>\n\n"
        f"{interpretation}"
    )


def format_quality_interpretation(quality_key: str, interpretation: str, date: str) -> str:
    """
    Форматирует интерпретацию дополнительного качества для отображения.
    
    Args:
        quality_key: Ключ качества (life, temperament, и т.д.)
        interpretation: Текст интерпретации
        date: Дата рождения
        
    Returns:
        Отформатированная строка
    """
    quality_name = QUALITY_NAMES[quality_key]
    
    return (
        f"🔮 <b>Результаты расчетов для {date}</b>\n\n"
        f"📚 <b>{quality_name}</b>\n\n"
        f"{interpretation}"
    )


def create_back_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопкой "Назад" для возврата к основному сообщению.
    
    Returns:
        InlineKeyboardMarkup с кнопкой "Назад"
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀ Назад", callback_data="back:main")
    ]])


@router.callback_query(F.data.startswith("sector:"))
async def handle_sector_callback(callback: CallbackQuery):
    """Обработчик нажатия на кнопку сектора."""
    await callback.answer()
    
    # Извлекаем ключ сектора из callback_data
    sector_key = callback.data.split(":")[1]
    
    # Получаем message_id исходного сообщения
    message_id = callback.message.message_id
    
    # Получаем сохраненные результаты
    if message_id not in _results_cache:
        await callback.message.edit_text(
            "❌ Ошибка: данные расчетов не найдены. Пожалуйста, отправьте дату заново.",
            parse_mode="HTML"
        )
        return
    
    cache_data = _results_cache[message_id]
    results = cache_data['results']
    date = cache_data['date']
    
    # Получаем интерпретации
    interpretations = get_all_interpretations(results)
    
    if sector_key not in interpretations:
        await callback.message.edit_text(
            "❌ Ошибка: сектор не найден.",
            parse_mode="HTML"
        )
        return
    
    # Форматируем интерпретацию
    interpretation_text = format_sector_interpretation(
        sector_key,
        interpretations[sector_key],
        date
    )
    
    # Создаем клавиатуру с кнопкой "Назад"
    keyboard = create_back_keyboard()
    
    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            interpretation_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        # Если сообщение слишком длинное, отправляем новое
        await callback.message.answer(
            interpretation_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )


@router.callback_query(F.data.startswith("quality:"))
async def handle_quality_callback(callback: CallbackQuery):
    """Обработчик нажатия на кнопку дополнительного качества."""
    await callback.answer()
    
    # Извлекаем ключ качества из callback_data
    quality_key = callback.data.split(":")[1]
    
    # Получаем message_id исходного сообщения
    message_id = callback.message.message_id
    
    # Получаем сохраненные результаты
    if message_id not in _results_cache:
        await callback.message.edit_text(
            "❌ Ошибка: данные расчетов не найдены. Пожалуйста, отправьте дату заново.",
            parse_mode="HTML"
        )
        return
    
    cache_data = _results_cache[message_id]
    results = cache_data['results']
    date = cache_data['date']
    
    # Получаем интерпретации дополнительных качеств
    qualities = get_additional_qualities(results)
    
    if quality_key not in qualities:
        await callback.message.edit_text(
            "❌ Ошибка: качество не найдено.",
            parse_mode="HTML"
        )
        return
    
    # Форматируем интерпретацию
    interpretation_text = format_quality_interpretation(
        quality_key,
        qualities[quality_key],
        date
    )
    
    # Создаем клавиатуру с кнопкой "Назад"
    keyboard = create_back_keyboard()
    
    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            interpretation_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        # Если сообщение слишком длинное, отправляем новое
        await callback.message.answer(
            interpretation_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )


@router.callback_query(F.data == "combos:show")
async def handle_combos_callback(callback: CallbackQuery):
    """Обработчик нажатия на кнопку 'Комбинации'."""
    await callback.answer()

    message_id = callback.message.message_id

    if message_id not in _results_cache:
        await callback.message.answer(
            "❌ Ошибка: данные расчётов не найдены. Пожалуйста, отправьте дату заново.",
            parse_mode="HTML"
        )
        return

    cache_data = _results_cache[message_id]
    results = cache_data['results']
    date = cache_data['date']

    matches = get_matching_combinations(results)

    if not matches:
        await callback.message.answer(
            f"🧩 <b>Комбинации для {date}</b>\n\n"
            "По текущим коэффициентам подходящих комбинаций не выявлено.",
            parse_mode="HTML"
        )
        return

    # Группируем тексты по разделам для удобного чтения
    text = f"🧩 <b>Комбинации для {date}</b>\n\n"
    current_group = None
    for group, combo_text in matches:
        if group != current_group:
            text += f"\n<b>🔹 {group}</b>\n\n"
            current_group = group
        text += f"• {combo_text}\n\n"

    await send_long_message(callback.message, text)


@router.callback_query(F.data == "back:main")
async def handle_back_callback(callback: CallbackQuery):
    """Обработчик нажатия на кнопку 'Назад'."""
    await callback.answer()
    
    # Получаем message_id исходного сообщения
    message_id = callback.message.message_id
    
    # Получаем сохраненные результаты
    if message_id not in _results_cache:
        await callback.message.edit_text(
            "❌ Ошибка: данные расчетов не найдены. Пожалуйста, отправьте дату заново.",
            parse_mode="HTML"
        )
        return
    
    cache_data = _results_cache[message_id]
    results = cache_data['results']
    
    # Формируем основной ответ
    response = format_results_basic(results)
    
    # Создаем клавиатуру с кнопками
    keyboard = create_inline_keyboard()
    
    # Редактируем сообщение обратно к основному виду
    try:
        await callback.message.edit_text(
            response,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        await callback.message.answer(
            response,
            parse_mode="HTML",
            reply_markup=keyboard
        )


@router.callback_query(F.data == "noop")
async def handle_noop_callback(callback: CallbackQuery):
    """Обработчик для неактивных кнопок (разделитель)."""
    await callback.answer()


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
        sector_name = SECTOR_NAMES[sector]
        if numbers:
            count = len(numbers)
            numbers_str = " ".join(str(n) for n in numbers)
            matrix_text += f"Сектор {sector} ({sector_name}): {numbers_str} (×{count})\n"
        else:
            matrix_text += f"Сектор {sector} ({sector_name}): пусто\n"
    
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
        f"⭐ <b>Число Судьбы:</b> {results['destiny_number']}\n\n"
        f"💡 <i>Нажмите на кнопку ниже, чтобы узнать интерпретацию сектора или дополнительного качества</i>"
    )
    
    return response


