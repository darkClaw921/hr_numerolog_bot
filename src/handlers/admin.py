"""
Панель админа /admin: переключение режима проверки (админ / пользователь без подписки /
пользователь с подпиской). Логика режимов — src/admin_mode.py.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.admin_mode import MODE_ADMIN, MODE_FREE, MODE_PREMIUM, MODE_TITLES, get_mode, is_admin_account, set_mode
from src.formatting import edit_or_send
from src.keyboards import CABINET_BUTTON

router = Router()

MODE_HINTS = {
    MODE_ADMIN: "Вы видите бот как админ: действует ваш реальный премиум, доступны /grant и /payments.",
    MODE_FREE: (
        "Вы видите бот как новый пользователь без подписки: платные разделы закрыты, "
        "в «Подписке» — оффер с настоящей ссылкой на оплату, админ-команды недоступны."
    ),
    MODE_PREMIUM: (
        "Вы видите бот как пользователь с подпиской: все разделы открыты, "
        "подписка имитируется (оплата и отмена не вызываются), админ-команды недоступны."
    ),
}


def _panel(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    mode = get_mode(telegram_id)
    text = (
        "🛠 <b>Панель админа</b>\n\n"
        f"Текущий режим: <b>{MODE_TITLES[mode]}</b>\n"
        f"{MODE_HINTS[mode]}\n\n"
        "Режим сбрасывается в «Админ» при перезапуске бота. Вернуться сюда — /admin."
    )
    rows = [
        [InlineKeyboardButton(text=("✅ " if key == mode else "") + title, callback_data=f"adm:mode:{key}")]
        for key, title in MODE_TITLES.items()
    ]
    rows.append([CABINET_BUTTON])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    # Для не-админов команда молчит так же, как любая неизвестная команда.
    if not is_admin_account(message.from_user.id):
        return
    text, keyboard = _panel(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("adm:mode:"))
async def cb_switch_mode(callback: CallbackQuery):
    if not is_admin_account(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    mode = callback.data.rsplit(":", 1)[1]
    if mode not in MODE_TITLES:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    set_mode(callback.from_user.id, mode)
    await callback.answer(f"Режим: {MODE_TITLES[mode]}")
    text, keyboard = _panel(callback.from_user.id)
    await edit_or_send(callback, text, keyboard)
