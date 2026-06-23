"""
Inline-клавиатуры бота.

Дата рождения зашита в callback_data (формат `тип:...:дата`), чтобы навигация по
кнопкам работала без хрупкого in-memory кэша и переживала рестарт бота:
результат детерминированно пересчитывается из даты.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.access import is_premium_feature
from src.texts import QUALITY_NAMES, QUALITY_ORDER, SECTOR_KEYS

# Обратное соответствие: номер сектора → строковый ключ.
SECTOR_NUM_TO_KEY = {num: key for key, num in SECTOR_KEYS.items()}


def create_result_keyboard(date: str, is_premium: bool, show_save: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура экрана результатов: отчёт, секторы, качества, комбинации, сохранение."""
    buttons: list[list[InlineKeyboardButton]] = []

    # Верхняя кнопка: полный общий отчёт (платно).
    report_text = "📄 Полный общий отчёт" if is_premium else "🔒 Полный общий отчёт"
    buttons.append([InlineKeyboardButton(text=report_text, callback_data=f"rep:{date}")])

    # Секторы 1-9 (по 3 в ряд).
    sector_row: list[InlineKeyboardButton] = []
    for sector_num in range(1, 10):
        key = SECTOR_NUM_TO_KEY[sector_num]
        sector_row.append(InlineKeyboardButton(text=str(sector_num), callback_data=f"sec:{key}:{date}"))
        if len(sector_row) == 3:
            buttons.append(sector_row)
            sector_row = []
    if sector_row:
        buttons.append(sector_row)

    # Разделитель.
    buttons.append([InlineKeyboardButton(text="━━━━━━━━━━━━━━━━", callback_data="noop")])

    # Дополнительные качества (по 2 в ряд). Платные помечаем замком для не-premium.
    quality_row: list[InlineKeyboardButton] = []
    for key in QUALITY_ORDER:
        name = QUALITY_NAMES[key].split()[0]
        locked = (not is_premium) and is_premium_feature(key)
        text = ("🔒 " + name) if locked else name
        quality_row.append(InlineKeyboardButton(text=text, callback_data=f"qual:{key}:{date}"))
        if len(quality_row) == 2:
            buttons.append(quality_row)
            quality_row = []
    if quality_row:
        buttons.append(quality_row)

    # Комбинации (платно).
    combos_text = "🧩 Комбинации" if is_premium else "🔒 Комбинации"
    buttons.append([InlineKeyboardButton(text=combos_text, callback_data=f"cmb:{date}")])

    # Сохранить человека в личный кабинет.
    if show_save:
        buttons.append([InlineKeyboardButton(text="💾 Сохранить человека", callback_data=f"save:{date}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_back_keyboard(date: str) -> InlineKeyboardMarkup:
    """Кнопка возврата к основному экрану результатов."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀ Назад", callback_data=f"bk:{date}")
    ]])


def cabinet_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню личного кабинета."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Мои люди", callback_data="cab:people")],
        [InlineKeyboardButton(text="🕘 История поисков", callback_data="cab:history")],
        [InlineKeyboardButton(text="➕ Добавить человека", callback_data="cab:add")],
    ])


def skip_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Пропустить» для опциональных шагов FSM (имя/ФИО)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="add:skip")
    ]])


def people_list_keyboard(people) -> InlineKeyboardMarkup:
    """Список сохранённых людей: кнопка на каждого открывает его профиль."""
    rows = []
    for person in people:
        label = person.display_name or person.full_name or "Без имени"
        date_str = person.birth_date.strftime("%d.%m.%Y")
        rows.append([InlineKeyboardButton(
            text=f"{label} ({date_str})", callback_data=f"pers:{person.id}"
        )])
    rows.append([InlineKeyboardButton(text="◀ В кабинет", callback_data="cab:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
