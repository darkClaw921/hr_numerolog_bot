"""
HTTP-приёмник уведомлений Prodamus (urlNotification).

Живёт в том же процессе, что и long polling: aiohttp-приложение поднимается через
AppRunner в `src.bot.main()`. Наружу путь вебхука проксирует reverse proxy по HTTPS.
"""
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot
from aiohttp import web

from src.config import (
    PRODAMUS_SECRET_KEY,
    PRODAMUS_WEBHOOK_PATH,
)
from src.db.session import async_session_factory
from src.payments import service
from src.payments.formdata import parse_php_form
from src.payments.hmac_sign import verify_signature
from src.texts import (
    SUB_NOTIFY_ACTIVATED,
    SUB_NOTIFY_CANCELLED,
    SUB_NOTIFY_FAILED,
    SUB_NOTIFY_RENEWED,
)

logger = logging.getLogger(__name__)

# Уведомление Prodamus — небольшая форма; всё, что крупнее, отбрасываем.
MAX_BODY_BYTES = 64 * 1024
# Простой лимит на путь вебхука; основная защита — reverse proxy.
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW_SEC = 60

_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)

# Типизированный ключ приложения (aiohttp рекомендует AppKey вместо строк).
BOT_KEY: web.AppKey[Bot | None] = web.AppKey("bot")


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    bucket = _requests_by_ip[ip]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SEC:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_REQUESTS:
        return True
    bucket.append(now)
    return False


def _format_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value is not None else "—"


async def _notify_user(bot: Bot, result: service.ApplyResult) -> None:
    """Сообщение пользователю после коммита; сбой Telegram не должен влиять на ответ."""
    if bot is None or result.telegram_id is None:
        return
    text = None
    if result.outcome == service.OUTCOME_ACTIVATED:
        text = SUB_NOTIFY_ACTIVATED.format(expires=_format_date(result.expires_at))
    elif result.outcome == service.OUTCOME_RENEWED:
        text = SUB_NOTIFY_RENEWED.format(expires=_format_date(result.expires_at))
    elif result.outcome == service.OUTCOME_CANCELLED:
        text = SUB_NOTIFY_CANCELLED.format(expires=_format_date(result.expires_at))
    elif result.outcome == service.OUTCOME_FAILED:
        text = SUB_NOTIFY_FAILED
    if text is None:
        return
    try:
        await bot.send_message(result.telegram_id, text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось отправить уведомление об оплате пользователю %s", result.telegram_id)


async def handle_notification(request: web.Request) -> web.Response:
    """POST urlNotification: проверяет подпись и применяет событие к подписке."""
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    if _rate_limited(ip):
        logger.warning("Prodamus: превышен лимит запросов с %s", ip)
        return web.Response(status=429, text="too many requests")

    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return web.Response(status=413, text="payload too large")

    try:
        raw = await request.text()
    except ValueError:
        return web.Response(status=413, text="payload too large")
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        return web.Response(status=413, text="payload too large")

    data = parse_php_form(raw)
    signature = request.headers.get("Sign") or request.headers.get("sign")
    if not verify_signature(data, PRODAMUS_SECRET_KEY, signature):
        # В лог — ничего секретного: только ключи payload и обрезанная подпись.
        logger.warning(
            "Prodamus: неверная подпись (order_id=%s, keys=%s, sign=%s…)",
            data.get("order_id"),
            sorted(data),
            (signature or "")[:8],
        )
        return web.Response(status=400, text="bad signature")

    try:
        async with async_session_factory() as session:
            result = await service.apply_notification(session, data, raw)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Prodamus: ошибка обработки уведомления (order_id=%s)", data.get("order_id"))
        # 500 → Prodamus повторит доставку; от двойного применения защищает event_key.
        return web.Response(status=500, text="internal error")

    logger.info(
        "Prodamus: order_id=%s status=%s → %s",
        result.order_id,
        data.get("payment_status"),
        result.outcome,
    )
    await _notify_user(request.app.get(BOT_KEY), result)
    return web.Response(status=200, text="OK")


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_webhook_app(bot: Bot | None = None) -> web.Application:
    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app[BOT_KEY] = bot
    app.router.add_post(PRODAMUS_WEBHOOK_PATH, handle_notification)
    app.router.add_get("/healthz", handle_health)
    return app
