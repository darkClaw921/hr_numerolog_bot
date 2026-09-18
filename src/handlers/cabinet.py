"""
Личный кабинет: сохранение людей (FSM), список сохранённых, история поисков,
реферальная программа. Экран подписки — в src/handlers/subscription.py.
"""
import html
import logging
import re
from datetime import datetime
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.config import REFERRAL_BONUS_DAYS
from src.db.models import BotUser
from src.db.repositories import PersonRepo, ReferralRepo, SearchHistoryRepo, SubscriptionRepo
from src.formatting import edit_or_send, person_label
from src.handlers.calculation import build_result_screen
from src.handlers.common import REFERRAL_PREFIX
from src.keyboards import (
    BACK_TO_CABINET_BUTTON,
    CABINET_BUTTON,
    back_to_cabinet_keyboard,
    cabinet_menu_keyboard,
    history_keyboard,
    people_list_keyboard,
    skip_keyboard,
)
from src.texts import REFERRAL_SHARE_TEXT, REFERRAL_TEXT
from src.utils.numerology import CALC_VERSION, calculate_all, format_date_for_calc, parse_date

logger = logging.getLogger(__name__)
router = Router()


class AddPerson(StatesGroup):
    waiting_date = State()
    waiting_name = State()
    waiting_full_name = State()


DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
# Лимиты колонок people.display_name / people.full_name.
MAX_NAME_LEN = 255
MAX_FULL_NAME_LEN = 512
# Telegram принимает не больше 100 кнопок в клавиатуре — показываем последних сохранённых.
MAX_PEOPLE_IN_LIST = 50


def _to_date(date_str: str):
    return datetime.strptime(date_str, "%d.%m.%Y").date()


def _label(person) -> str:
    return person_label(person.display_name, person.full_name)


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✖ Отмена", callback_data="add:cancel")
    ]])


def _skip_or_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[*skip_keyboard().inline_keyboard, *_cancel_keyboard().inline_keyboard])


# ---------- Меню кабинета ----------

CABINET_INTRO = (
    "👤 <b>Личный кабинет</b>\n\n"
    "Здесь хранятся сохранённые люди, история ваших поисков, подписка и бонусы.\n\n"
    "📅 Чтобы сделать новый расчёт, просто отправьте дату рождения (DD.MM.YYYY)."
)


@router.message(Command("menu", "cabinet"))
async def cmd_cabinet(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(CABINET_INTRO, parse_mode="HTML", reply_markup=cabinet_menu_keyboard())


@router.callback_query(F.data == "cab:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await edit_or_send(callback, CABINET_INTRO, cabinet_menu_keyboard())


@router.callback_query(F.data == "cab:people")
async def cb_people(callback: CallbackQuery, person_repo: PersonRepo, db_user: BotUser):
    await callback.answer()
    people = await person_repo.list(db_user.id)
    if not people:
        await edit_or_send(
            callback,
            "👥 Пока нет сохранённых людей.\n\n"
            "Сделайте расчёт по дате и нажмите «💾 Сохранить человека» или «➕ Добавить человека» в кабинете.",
            back_to_cabinet_keyboard(),
        )
        return
    header = "👥 <b>Мои люди</b>\n\nВыберите человека:"
    if len(people) > MAX_PEOPLE_IN_LIST:
        header += f"\n<i>Показаны последние {MAX_PEOPLE_IN_LIST} из {len(people)}.</i>"
    await edit_or_send(callback, header, people_list_keyboard(people[:MAX_PEOPLE_IN_LIST], _label))


@router.callback_query(F.data == "cab:history")
async def cb_history(callback: CallbackQuery, history_repo: SearchHistoryRepo, db_user: BotUser):
    await callback.answer()
    items = await history_repo.list_unique(db_user.id, limit=15)
    if not items:
        await edit_or_send(callback, "🕘 История поисков пуста.", back_to_cabinet_keyboard())
        return
    await edit_or_send(
        callback,
        "🕘 <b>История поисков</b>\n\nКого вы искали (последние сверху). Нажмите, чтобы открыть:",
        history_keyboard(items, _label),
    )


@router.callback_query(F.data == "cab:ref")
async def cb_referral(callback: CallbackQuery, referral_repo: ReferralRepo, db_user: BotUser):
    """Бонус: реферальная ссылка и статистика приглашений."""
    await callback.answer()
    me = await callback.bot.me()
    link = f"https://t.me/{me.username}?start={REFERRAL_PREFIX}{db_user.id}"
    stats = await referral_repo.stats(db_user.id)
    text = REFERRAL_TEXT.format(days=REFERRAL_BONUS_DAYS, link=link, **stats)
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(REFERRAL_SHARE_TEXT, safe='')}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url)],
        [BACK_TO_CABINET_BUTTON],
    ])
    await edit_or_send(callback, text, keyboard)


# ---------- Открытие сохранённого человека ----------

@router.callback_query(F.data.startswith("pers:"))
async def cb_person_open(
    callback: CallbackQuery,
    person_repo: PersonRepo,
    history_repo: SearchHistoryRepo,
    subscription_repo: SubscriptionRepo,
    db_user: BotUser,
):
    await callback.answer()
    raw_id = callback.data.split(":", 1)[1]
    person = await person_repo.get(int(raw_id), db_user.id) if raw_id.isdigit() else None
    if person is None:
        await edit_or_send(callback, "❌ Человек не найден.", back_to_cabinet_keyboard())
        return

    date_str = format_date_for_calc(person.birth_date)
    text, keyboard = await build_result_screen(date_str, db_user, subscription_repo, person)
    await edit_or_send(callback, text, keyboard)

    try:
        await history_repo.add(
            user_id=db_user.id, birth_date=person.birth_date, person_id=person.id, raw_query=date_str
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось записать историю поиска")


# ---------- FSM добавления человека ----------

@router.callback_query(F.data == "cab:add")
async def cb_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddPerson.waiting_date)
    await edit_or_send(callback, "📅 Введите дату рождения человека в формате DD.MM.YYYY:", _cancel_keyboard())


@router.callback_query(F.data.startswith("save:"))
async def cb_save_from_result(
    callback: CallbackQuery,
    state: FSMContext,
    person_repo: PersonRepo,
    subscription_repo: SubscriptionRepo,
    db_user: BotUser,
):
    """Сохранение человека прямо из экрана результатов: дата уже известна."""
    date_str = callback.data.split(":", 1)[1]
    try:
        parse_date(date_str)
    except ValueError:
        await callback.answer("❌ Некорректная дата", show_alert=True)
        return
    # Кнопка могла остаться на старом экране в истории чата — повторно не сохраняем,
    # а показываем профиль. Второго человека с той же датой можно добавить через «➕ Добавить».
    existing = await person_repo.find_by_birth_date(db_user.id, _to_date(date_str))
    if existing is not None:
        await callback.answer("Этот человек уже сохранён")
        text, keyboard = await build_result_screen(date_str, db_user, subscription_repo, existing)
        await edit_or_send(callback, text, keyboard)
        return
    await callback.answer()
    await state.set_state(AddPerson.waiting_name)
    # Запоминаем экран результатов: после сохранения уберём с него кнопку «Сохранить».
    await state.update_data(date=date_str, origin_message_id=callback.message.message_id)
    await callback.message.answer(
        f"💾 Сохраняю человека с датой {date_str}.\n\nВведите имя или пропустите:",
        reply_markup=_skip_or_cancel_keyboard(),
    )


@router.callback_query(F.data == "add:cancel")
async def cb_add_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    await edit_or_send(callback, CABINET_INTRO, cabinet_menu_keyboard())


@router.message(AddPerson.waiting_date, ~F.text.startswith("/"))
async def fsm_date(message: Message, state: FSMContext):
    date_str = (message.text or "").strip()
    try:
        parse_date(date_str)
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Введите дату как DD.MM.YYYY (например, 18.08.1984):",
            reply_markup=_cancel_keyboard(),
        )
        return
    await state.update_data(date=date_str)
    await state.set_state(AddPerson.waiting_name)
    await message.answer("Введите имя человека или пропустите:", reply_markup=_skip_or_cancel_keyboard())


async def _reject_name(message: Message) -> bool:
    """
    Дата вместо имени — скорее всего, пользователь передумал сохранять и хочет новый
    расчёт: не записываем её в имя, а подсказываем, как выйти.
    """
    text = (message.text or "").strip()
    if DATE_RE.match(text):
        await message.answer(
            "Похоже, это дата, а не имя. Введите имя, пропустите шаг или нажмите «Отмена», "
            "чтобы сделать новый расчёт.",
            reply_markup=_skip_or_cancel_keyboard(),
        )
        return True
    if not text:
        await message.answer("Отправьте имя текстом или пропустите шаг.", reply_markup=_skip_or_cancel_keyboard())
        return True
    return False


# Команды (/cancel, /help…) не перехватываем как имя — их обработают командные хендлеры.
@router.message(AddPerson.waiting_name, ~F.text.startswith("/"))
async def fsm_name(message: Message, state: FSMContext):
    if await _reject_name(message):
        return
    await state.update_data(name=message.text.strip()[:MAX_NAME_LEN])
    await state.set_state(AddPerson.waiting_full_name)
    await message.answer("Введите ФИО (не обязательно) или пропустите:", reply_markup=_skip_or_cancel_keyboard())


@router.callback_query(AddPerson.waiting_name, F.data == "add:skip")
async def fsm_name_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(name=None)
    await state.set_state(AddPerson.waiting_full_name)
    await callback.message.answer(
        "Введите ФИО (не обязательно) или пропустите:", reply_markup=_skip_or_cancel_keyboard()
    )


@router.message(AddPerson.waiting_full_name, ~F.text.startswith("/"))
async def fsm_full_name(
    message: Message,
    state: FSMContext,
    person_repo: PersonRepo,
    subscription_repo: SubscriptionRepo,
    db_user: BotUser,
):
    if await _reject_name(message):
        return
    await state.update_data(full_name=message.text.strip()[:MAX_FULL_NAME_LEN])
    await _finalize_add(message, state, person_repo, subscription_repo, db_user)


@router.callback_query(AddPerson.waiting_full_name, F.data == "add:skip")
async def fsm_full_name_skip(
    callback: CallbackQuery,
    state: FSMContext,
    person_repo: PersonRepo,
    subscription_repo: SubscriptionRepo,
    db_user: BotUser,
):
    await callback.answer()
    await state.update_data(full_name=None)
    await _finalize_add(callback.message, state, person_repo, subscription_repo, db_user)


async def _finalize_add(
    target: Message,
    state: FSMContext,
    person_repo: PersonRepo,
    subscription_repo: SubscriptionRepo,
    db_user: BotUser,
):
    data = await state.get_data()
    await state.clear()
    date_str = data["date"]
    name = data.get("name") or None
    full_name = data.get("full_name") or None

    snapshot = calculate_all(date_str)
    person = await person_repo.add(
        owner_user_id=db_user.id,
        birth_date=_to_date(date_str),
        display_name=name,
        full_name=full_name,
        calc_snapshot=snapshot,
        calc_version=CALC_VERSION,
        destiny_number=snapshot["destiny_number"],
    )

    # Человек сохранён — экран результатов, с которого сохраняли, становится его профилем
    # (без кнопки «Сохранить»). Сообщение могло устареть — тогда просто пропускаем.
    origin_id = data.get("origin_message_id")
    if origin_id:
        try:
            text, keyboard = await build_result_screen(date_str, db_user, subscription_repo, person)
            await target.bot.edit_message_text(
                text, chat_id=target.chat.id, message_id=origin_id, parse_mode="HTML", reply_markup=keyboard
            )
        except Exception:  # noqa: BLE001
            logger.info("Не удалось обновить экран результатов после сохранения", exc_info=True)

    label = person_label(name, full_name)
    await target.answer(
        f"✅ Сохранено: <b>{html.escape(label[:100])}</b> ({date_str}).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Открыть профиль", callback_data=f"pers:{person.id}")],
            [CABINET_BUTTON],
        ]),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_cabinet_keyboard())


@router.message(StateFilter(AddPerson), F.text.startswith("/"))
async def fsm_unknown_command(message: Message):
    """Неизвестная команда во время сохранения: не записываем её в имя и не молчим."""
    await message.answer(
        "Сейчас идёт сохранение человека. Введите данные, нажмите «Отмена» или /cancel.",
        reply_markup=_cancel_keyboard(),
    )


# Регистрируется последним: срабатывает, только если «Пропустить» не подошёл ни одному
# шагу FSM (кнопка со старого сообщения после завершения или отмены сохранения).
@router.callback_query(F.data == "add:skip")
async def cb_skip_stale(callback: CallbackQuery):
    await callback.answer("Сохранение уже завершено или отменено", show_alert=True)
