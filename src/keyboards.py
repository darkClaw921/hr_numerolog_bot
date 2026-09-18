"""
Inline-клавиатуры бота.

Дата рождения зашита в callback_data (формат `тип:...:дата`), чтобы навигация по
кнопкам работала без хрупкого in-memory кэша и переживала рестарт бота:
результат детерминированно пересчитывается из даты.

Если экран открыт из профиля сохранённого человека, в конец callback_data
добавляется `:<person_id>` — по нему кнопки «Назад» возвращают в профиль.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.access import is_premium_feature
from src.texts import QUALITY_BUTTONS, QUALITY_ORDER, SECTOR_KEYS

# Обратное соответствие: номер сектора → строковый ключ.
SECTOR_NUM_TO_KEY = {num: key for key, num in SECTOR_KEYS.items()}

CABINET_BUTTON = InlineKeyboardButton(text="🏠 Личный кабинет", callback_data="cab:menu")
BACK_TO_CABINET_BUTTON = InlineKeyboardButton(text="◀ В кабинет", callback_data="cab:menu")


# Подпись кнопки с именем: длинные имена обрезаем, чтобы кнопка оставалась читаемой.
MAX_BUTTON_LABEL = 40


def _short(label: str) -> str:
    return label if len(label) <= MAX_BUTTON_LABEL else label[: MAX_BUTTON_LABEL - 1] + "…"


def _ctx(person_id: int | None) -> str:
    """Суффикс callback_data с id профиля человека (пусто вне профиля)."""
    return f":{person_id}" if person_id else ""


def split_callback(data: str, fields: int) -> tuple[list[str], int | None]:
    """
    Разбирает callback_data на `fields` обязательных частей (включая префикс) и
    необязательный id профиля человека в конце.
    """
    parts = data.split(":")
    person_id = None
    if len(parts) > fields and parts[fields].isdigit():
        person_id = int(parts[fields])
    return parts[:fields], person_id


def create_result_keyboard(
    date: str,
    is_premium: bool,
    person_id: int | None = None,
    show_save: bool = True,
) -> InlineKeyboardMarkup:
    """
    Клавиатура экрана результатов: отчёт, секторы, качества, комбинации и навигация.

    person_id — экран является профилем сохранённого человека: кнопки «Сохранить»
    нет, внизу «Назад» к списку людей и «Личный кабинет».
    """
    ctx = _ctx(person_id)
    buttons: list[list[InlineKeyboardButton]] = []

    # Верхняя кнопка: полный общий отчёт (платно).
    report_text = "📄 Полный общий отчёт" if is_premium else "🔒 Полный общий отчёт"
    buttons.append([InlineKeyboardButton(text=report_text, callback_data=f"rep:{date}{ctx}")])

    # Секторы 1-9 (по 3 в ряд).
    sector_row: list[InlineKeyboardButton] = []
    for sector_num in range(1, 10):
        key = SECTOR_NUM_TO_KEY[sector_num]
        sector_row.append(InlineKeyboardButton(text=str(sector_num), callback_data=f"sec:{key}:{date}{ctx}"))
        if len(sector_row) == 3:
            buttons.append(sector_row)
            sector_row = []
    if sector_row:
        buttons.append(sector_row)

    # Дополнительные качества (по 2 в ряд). Платные помечаем замком для не-premium.
    quality_row: list[InlineKeyboardButton] = []
    for key in QUALITY_ORDER:
        name = QUALITY_BUTTONS[key]
        locked = (not is_premium) and is_premium_feature(key)
        text = ("🔒 " + name) if locked else name
        quality_row.append(InlineKeyboardButton(text=text, callback_data=f"qual:{key}:{date}{ctx}"))
        if len(quality_row) == 2:
            buttons.append(quality_row)
            quality_row = []
    if quality_row:
        buttons.append(quality_row)

    # Комбинации (платно).
    combos_text = "🧩 Комбинации" if is_premium else "🔒 Комбинации"
    buttons.append([InlineKeyboardButton(text=combos_text, callback_data=f"cmb:{date}{ctx}")])

    if person_id:
        buttons.append([InlineKeyboardButton(text="◀ Назад к людям", callback_data="cab:people")])
    elif show_save:
        buttons.append([InlineKeyboardButton(text="💾 Сохранить человека", callback_data=f"save:{date}")])
    buttons.append([CABINET_BUTTON])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_back_keyboard(date: str, person_id: int | None = None) -> InlineKeyboardMarkup:
    """Кнопка возврата к экрану результатов (в профиль, если он открыт из профиля)."""
    text = "◀ Назад в профиль" if person_id else "◀ Назад"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=f"bk:{date}{_ctx(person_id)}")
    ]])


def cabinet_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню личного кабинета."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Мои люди", callback_data="cab:people")],
        [InlineKeyboardButton(text="🕘 История поисков", callback_data="cab:history")],
        [InlineKeyboardButton(text="➕ Добавить человека", callback_data="cab:add")],
        [InlineKeyboardButton(text="💎 Подписка", callback_data="cab:sub")],
        [InlineKeyboardButton(text="🎁 Бонус: пригласи друга", callback_data="cab:ref")],
    ])


def back_to_cabinet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[BACK_TO_CABINET_BUTTON]])


def skip_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Пропустить» для опциональных шагов FSM (имя/ФИО)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="add:skip")
    ]])


def people_list_keyboard(people, label_of) -> InlineKeyboardMarkup:
    """Список сохранённых людей: кнопка на каждого открывает его профиль."""
    rows = []
    for person in people:
        date_str = person.birth_date.strftime("%d.%m.%Y")
        rows.append([InlineKeyboardButton(
            text=f"{_short(label_of(person))} ({date_str})", callback_data=f"pers:{person.id}"
        )])
    rows.append([BACK_TO_CABINET_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_keyboard(items, label_of) -> InlineKeyboardMarkup:
    """
    История поисков списком: сохранённый человек открывает профиль, поиск
    «на лету» — экран результатов по дате.
    """
    rows = []
    for item, person in items:
        date_str = item.birth_date.strftime("%d.%m.%Y")
        if person is not None:
            text = f"👤 {_short(label_of(person))} ({date_str})"
            data = f"pers:{person.id}"
        else:
            text = f"📅 {date_str}"
            data = f"bk:{date_str}"
        rows.append([InlineKeyboardButton(text=text, callback_data=data)])
    rows.append([BACK_TO_CABINET_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def paywall_keyboard(back_data: str | None = None) -> InlineKeyboardMarkup:
    """Пейволл: переход к подписке и (если известно куда) возврат назад."""
    rows = [[InlineKeyboardButton(text="💎 Оформить подписку", callback_data="cab:sub")]]
    if back_data:
        rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
