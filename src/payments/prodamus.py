"""
Клиент Prodamus: сборка ссылки на оплату подписки и REST-вызовы управления подпиской.
"""
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import aiohttp

from src.config import (
    PRODAMUS_DEMO_MODE,
    PRODAMUS_FORM_URL,
    PRODAMUS_SECRET_KEY,
    PRODAMUS_SUBSCRIPTION_ID,
    PRODAMUS_SYS,
    PRODAMUS_TRIAL_DAYS,
    PRODAMUS_WEBHOOK_PATH,
    PUBLIC_BASE_URL,
)
from src.payments.hmac_sign import create_signature

logger = logging.getLogger(__name__)

# Таймаут REST-вызовов: подписи считаются локально, сеть нужна только для setActivity.
_REST_TIMEOUT = aiohttp.ClientTimeout(total=15)


def notification_url() -> str:
    """Публичный адрес, на который Prodamus присылает уведомления об оплате."""
    return f"{PUBLIC_BASE_URL}{PRODAMUS_WEBHOOK_PATH}"


def _return_url(bot_username: str) -> str:
    """Возврат пользователя после оплаты — сразу в бот, отдельные страницы не нужны."""
    return f"https://t.me/{bot_username}"


def build_payment_link(
    *,
    order_id: str,
    telegram_id: int,
    bot_username: str,
    customer_phone: str | None = None,
    customer_email: str | None = None,
    trial_days: int | None = None,
) -> str:
    """
    Собирает подписанную ссылку на оплату подписки.

    Подпись считается по ДЕКОДИРОВАННЫМ значениям, urlencode применяется после —
    иначе подпись не сойдётся на стороне Prodamus.
    """
    return_url = _return_url(bot_username)
    params: dict[str, str] = {
        "do": "pay",
        "order_id": order_id,
        "subscription": PRODAMUS_SUBSCRIPTION_ID,
        # customer_extra возвращается в уведомлении — запасной канал идентификации.
        "customer_extra": f"tg:{telegram_id}",
        "urlReturn": return_url,
        "urlSuccess": return_url,
        "urlNotification": notification_url(),
    }

    days = PRODAMUS_TRIAL_DAYS if trial_days is None else trial_days
    if days > 0:
        # Пробный период: первое списание откладывается на указанную дату.
        start = datetime.now(timezone.utc) + timedelta(days=days)
        params["subscription_date_start"] = start.strftime("%Y-%m-%d %H:%M:%S")

    if customer_phone:
        params["customer_phone"] = customer_phone
    if customer_email:
        params["customer_email"] = customer_email
    if PRODAMUS_SYS:
        params["sys"] = PRODAMUS_SYS
    if PRODAMUS_DEMO_MODE:
        params["demo_mode"] = "1"

    params["signature"] = create_signature(params, PRODAMUS_SECRET_KEY)
    return f"{PRODAMUS_FORM_URL}/?{urlencode(params, quote_via=quote)}"


async def set_activity(
    *,
    active_manager: bool | None = None,
    active_user: bool | None = None,
    subscription_id: str | None = None,
    customer_phone: str | None = None,
    customer_email: str | None = None,
    tg_user_id: int | None = None,
) -> dict:
    """
    Активирует/деактивирует подписку (REST-метод setActivity).

    Не бросает исключений: возвращает {"ok", "status", "body"} — вызывающий хендлер
    сам решает, что показать пользователю.
    """
    data: dict[str, str] = {"subscription": subscription_id or PRODAMUS_SUBSCRIPTION_ID}
    if customer_phone:
        data["customer_phone"] = customer_phone
    if customer_email:
        data["customer_email"] = customer_email
    if tg_user_id is not None:
        data["tg_user_id"] = str(tg_user_id)
    if active_manager is not None:
        data["active_manager"] = "1" if active_manager else "0"
    if active_user is not None:
        # Пользователь может только отписаться — обратная активация только менеджером.
        data["active_user"] = "1" if active_user else "0"
    data["signature"] = create_signature(data, PRODAMUS_SECRET_KEY)

    url = f"{PRODAMUS_FORM_URL}/rest/setActivity/"
    try:
        async with aiohttp.ClientSession(timeout=_REST_TIMEOUT) as session:
            async with session.post(url, data=data) as response:
                body = await response.text()
                ok = response.status == 200
                if not ok:
                    logger.warning("Prodamus setActivity: HTTP %s, ответ: %s", response.status, body[:500])
                return {"ok": ok, "status": response.status, "body": body}
    except Exception as exc:  # noqa: BLE001 — сеть не должна ронять хендлер
        logger.exception("Prodamus setActivity: запрос не удался")
        return {"ok": False, "status": 0, "body": str(exc)}
