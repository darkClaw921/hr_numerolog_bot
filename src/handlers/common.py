"""
Общие команды: /start (в т.ч. по реферальной ссылке) и /help.
"""
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, InlineKeyboardMarkup, Message

from src.config import REFERRAL_BONUS_DAYS
from src.db.models import BotUser
from src.db.repositories import PaymentRepo, ReferralRepo, SubscriptionRepo, UserRepo
from src.keyboards import CABINET_BUTTON
from src.texts import REFERRAL_JOINED_NOTIFY

logger = logging.getLogger(__name__)
router = Router()

# Префикс deep-link параметра реферальной ссылки: t.me/<bot>?start=ref_<bot_users.id>.
REFERRAL_PREFIX = "ref_"

# Команды в кнопке «Меню» Telegram (ТЗ 06, п. 2). Остальные команды работают, но не показываются.
BOT_COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="menu", description="Личный кабинет"),
]
ADMIN_BOT_COMMANDS = [*BOT_COMMANDS, BotCommand(command="admin", description="Режим админа / пользователя")]


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[CABINET_BUTTON]])


async def _attach_referral(
    message: Message,
    payload: str,
    db_user: BotUser,
    user_repo: UserRepo,
    referral_repo: ReferralRepo,
    subscription_repo: SubscriptionRepo,
    payment_repo: PaymentRepo,
) -> None:
    """
    Привязывает нового пользователя к пригласившему. Бонус пригласившему начисляется
    позже — при первой оплате подписки приглашённым (src/payments/service.py).

    Не привязываем тех, кто уже платил или имел подписку: приглашать имеет смысл
    только новых клиентов.
    """
    raw_id = payload[len(REFERRAL_PREFIX):]
    # Длину ограничиваем: огромное число не влезает в SQLite INTEGER (OverflowError).
    if not raw_id.isdigit() or len(raw_id) > 18:
        return
    referrer = await user_repo.session.get(BotUser, int(raw_id))
    if referrer is None or referrer.id == db_user.id:
        return
    if await subscription_repo.get(db_user.id) is not None:
        return
    if await payment_repo.list_by_user(db_user.id, limit=1):
        return
    if await referral_repo.attach(referrer.id, db_user.id) is None:
        return
    logger.info("Реферал: user=%s пришёл по ссылке user=%s", db_user.id, referrer.id)
    try:
        await message.bot.send_message(referrer.telegram_id, REFERRAL_JOINED_NOTIFY.format(days=REFERRAL_BONUS_DAYS))
    except Exception:  # noqa: BLE001 — уведомление не должно ломать /start
        logger.info("Не удалось уведомить пригласившего %s", referrer.telegram_id, exc_info=True)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db_user: BotUser,
    user_repo: UserRepo,
    referral_repo: ReferralRepo,
    subscription_repo: SubscriptionRepo,
    payment_repo: PaymentRepo,
):
    """Обработчик команды /start; `/start ref_<id>` — вход по реферальной ссылке."""
    await state.clear()
    payload = (command.args or "").strip()
    if payload.startswith(REFERRAL_PREFIX):
        await _attach_referral(
            message, payload, db_user, user_repo, referral_repo, subscription_repo, payment_repo
        )

    await message.answer(
        "👋 Привет! Я бот для нумерологических расчетов по дате рождения.\n\n"
        "📅 Отправьте мне дату рождения в формате DD.MM.YYYY\n"
        "Например: 18.08.1984\n\n"
        "В личном кабинете (/menu) можно сохранять людей, смотреть историю поисков, "
        "управлять подпиской и приглашать друзей.\n"
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
        "/menu — Личный кабинет (люди, история, подписка, бонусы)\n"
        "/help — Показать эту справку\n\n"
        "🔒 — платные функции (полный отчёт, комбинации, часть коэффициентов)."
    )
