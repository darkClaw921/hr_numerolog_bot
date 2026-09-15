"""
Личный кабинет: сохранение людей (FSM), список сохранённых, история поисков.
"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.db.models import BotUser
from src.db.repositories import (
    PaymentIntentRepo,
    PersonRepo,
    SearchHistoryRepo,
    SubscriptionRepo,
)
from src.formatting import person_label
from src.handlers.calculation import render_result
from src.handlers.subscription import render_subscription_screen
from src.keyboards import cabinet_menu_keyboard, people_list_keyboard, skip_keyboard
from src.utils.numerology import CALC_VERSION, calculate_all, format_date_for_calc, parse_date

logger = logging.getLogger(__name__)
router = Router()


class AddPerson(StatesGroup):
    waiting_date = State()
    waiting_name = State()
    waiting_full_name = State()


def _to_date(date_str: str):
    return datetime.strptime(date_str, "%d.%m.%Y").date()


# ---------- Меню кабинета ----------

CABINET_INTRO = (
    "👤 <b>Личный кабинет</b>\n\n"
    "Здесь хранятся сохранённые люди и история ваших поисков."
)


@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    await message.answer(CABINET_INTRO, parse_mode="HTML", reply_markup=cabinet_menu_keyboard())


@router.callback_query(F.data == "cab:menu")
async def cb_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(CABINET_INTRO, parse_mode="HTML", reply_markup=cabinet_menu_keyboard())


@router.callback_query(F.data == "cab:people")
async def cb_people(callback: CallbackQuery, person_repo: PersonRepo, db_user: BotUser):
    await callback.answer()
    people = await person_repo.list(db_user.id)
    if not people:
        await callback.message.answer(
            "У вас пока нет сохранённых людей. Рассчитайте дату и нажмите «💾 Сохранить человека», "
            "либо добавьте через меню кабинета.",
        )
        return
    await callback.message.answer("👥 <b>Ваши люди:</b>", parse_mode="HTML",
                                  reply_markup=people_list_keyboard(people))


@router.callback_query(F.data == "cab:history")
async def cb_history(callback: CallbackQuery, history_repo: SearchHistoryRepo, db_user: BotUser):
    await callback.answer()
    items = await history_repo.list(db_user.id, limit=20)
    if not items:
        await callback.message.answer("🕘 История поисков пуста.")
        return
    lines = ["🕘 <b>История поисков:</b>\n"]
    for item in items:
        when = item.created_at.strftime("%d.%m.%Y %H:%M") if item.created_at else ""
        date_str = item.birth_date.strftime("%d.%m.%Y")
        lines.append(f"• {date_str} <i>({when})</i>")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "cab:sub")
async def cb_subscription(
    callback: CallbackQuery,
    subscription_repo: SubscriptionRepo,
    intent_repo: PaymentIntentRepo,
    db_user: BotUser,
):
    """Экран подписки из кабинета — тот же, что у /subscribe."""
    await callback.answer()
    await render_subscription_screen(callback.message, db_user, subscription_repo, intent_repo)


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
    person_id = int(callback.data.split(":", 1)[1])
    person = await person_repo.get(person_id, db_user.id)
    if person is None:
        await callback.message.answer("❌ Человек не найден.")
        return

    date_str = format_date_for_calc(person.birth_date)
    label = person_label(person.display_name, person.full_name)
    await callback.message.answer(f"📂 <b>{label}</b>", parse_mode="HTML")
    await render_result(callback.message, date_str, db_user, subscription_repo, show_save=False)

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
    await callback.message.answer("📅 Введите дату рождения человека в формате DD.MM.YYYY:")


@router.callback_query(F.data.startswith("save:"))
async def cb_save_from_result(callback: CallbackQuery, state: FSMContext):
    """Сохранение человека прямо из экрана результатов: дата уже известна."""
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    await state.set_state(AddPerson.waiting_name)
    await state.update_data(date=date_str)
    await callback.message.answer(
        f"💾 Сохраняю человека с датой {date_str}.\n\nВведите имя или пропустите:",
        reply_markup=skip_keyboard(),
    )


@router.message(AddPerson.waiting_date)
async def fsm_date(message: Message, state: FSMContext):
    date_str = (message.text or "").strip()
    try:
        parse_date(date_str)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите дату как DD.MM.YYYY (например, 18.08.1984):")
        return
    await state.update_data(date=date_str)
    await state.set_state(AddPerson.waiting_name)
    await message.answer("Введите имя человека или пропустите:", reply_markup=skip_keyboard())


@router.message(AddPerson.waiting_name)
async def fsm_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(AddPerson.waiting_full_name)
    await message.answer("Введите ФИО или пропустите:", reply_markup=skip_keyboard())


@router.callback_query(AddPerson.waiting_name, F.data == "add:skip")
async def fsm_name_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(name=None)
    await state.set_state(AddPerson.waiting_full_name)
    await callback.message.answer("Введите ФИО или пропустите:", reply_markup=skip_keyboard())


@router.message(AddPerson.waiting_full_name)
async def fsm_full_name(message: Message, state: FSMContext, person_repo: PersonRepo, db_user: BotUser):
    await state.update_data(full_name=(message.text or "").strip())
    await _finalize_add(message, state, person_repo, db_user)


@router.callback_query(AddPerson.waiting_full_name, F.data == "add:skip")
async def fsm_full_name_skip(
    callback: CallbackQuery, state: FSMContext, person_repo: PersonRepo, db_user: BotUser
):
    await callback.answer()
    await state.update_data(full_name=None)
    await _finalize_add(callback.message, state, person_repo, db_user)


async def _finalize_add(target: Message, state: FSMContext, person_repo: PersonRepo, db_user: BotUser):
    data = await state.get_data()
    await state.clear()
    date_str = data["date"]
    name = data.get("name") or None
    full_name = data.get("full_name") or None

    snapshot = calculate_all(date_str)
    await person_repo.add(
        owner_user_id=db_user.id,
        birth_date=_to_date(date_str),
        display_name=name,
        full_name=full_name,
        calc_snapshot=snapshot,
        calc_version=CALC_VERSION,
        destiny_number=snapshot["destiny_number"],
    )
    label = person_label(name, full_name)
    await target.answer(
        f"✅ Сохранено: <b>{label}</b> ({date_str}).\n"
        "Открыть его можно в кабинете: /cabinet → «Мои люди».",
        parse_mode="HTML",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        await state.clear()
        await message.answer("Отменено.")
