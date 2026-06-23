"""
Общие команды: /start и /help.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 Личный кабинет", callback_data="cab:menu")
    ]])


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    await message.answer(
        "👋 Привет! Я бот для нумерологических расчетов по дате рождения.\n\n"
        "📅 Отправьте мне дату рождения в формате DD.MM.YYYY\n"
        "Например: 18.08.1984\n\n"
        "В личном кабинете можно сохранять людей и смотреть историю поисков.\n"
        "Используйте /help для получения справки.",
        reply_markup=_start_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    await message.answer(
        "📖 Справка по использованию бота:\n\n"
        "Отправьте дату рождения в формате DD.MM.YYYY\n"
        "Например: 18.08.1984 или 05.12.1990\n\n"
        "Бот рассчитает матрицу, коэффициенты секторов, Число Судьбы и даст "
        "интерпретации по кнопкам.\n\n"
        "Команды:\n"
        "/start — Начать работу\n"
        "/help — Показать эту справку\n"
        "/cabinet — Личный кабинет (сохранённые люди, история)\n"
        "/subscribe — Информация о подписке\n\n"
        "🔒 — платные функции (полный отчёт, комбинации, часть коэффициентов)."
    )
