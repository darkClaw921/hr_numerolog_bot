"""
HTTP-приёмник уведомлений Prodamus.

Prodamus шлёт уведомления POST-запросом в multipart/form-data на адреса из настроек ЛК
(«Настройки» → «URL адреса для уведомлений», для клубов — ещё и в разделе «Подписки»);
параметр urlNotification в ссылке он не использует.

Живёт в том же процессе, что и long polling: aiohttp-приложение поднимается через
AppRunner в `src.bot.main()`. Наружу путь вебхука проксирует reverse proxy по HTTPS.
"""
import asyncio
import logging
import time
from collections import defaultdict, deque
from urllib.parse import urlencode

from aiogram import Bot
from aiohttp import web

from src.config import (
    PRODAMUS_GRACE_DAYS,
    PRODAMUS_SECRET_KEY,
    PRODAMUS_WEBHOOK_PATH,
)
from src.db.repositories import SubscriptionRepo
from src.db.session import async_session_factory
from src.payments import prodamus, service
from src.payments.formdata import parse_php_pairs
from src.payments.hmac_sign import verify_signature
from src.texts import (
    REFERRAL_REWARD_NOTIFY,
    REFERRAL_REWARD_NOTIFY_LIFETIME,
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


async def _read_form_pairs(request: web.Request) -> list[tuple[str, str]]:
    """
    Поля формы как пары (ключ, значение) — и для multipart/form-data, и для urlencoded.
    Файловые части (в уведомлениях их не бывает) пропускаются.
    """
    form = await request.post()
    return [(key, value) for key, value in form.items() if isinstance(value, str)]


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
        return
    logger.info("Уведомление «%s» отправлено пользователю %s", result.outcome, result.telegram_id)


async def _apply_referral_reward(bot: Bot | None, reward: service.ReferralReward) -> None:
    """
    После коммита: сдвигает дату автосписания в Prodamus на бонусные дни и сообщает о бонусе.

    Без переноса бонус «съел» бы очередной оплаченный период: доступ считается от даты
    списания. Если перенос не удался, дни записываются в отложенные и перенос повторяется
    при следующем успешном списании (ApplyResult.pending_shift).
    """
    if reward.shift_to is not None and reward.shift_phone:
        response = await prodamus.set_payment_date(
            customer_phone=reward.shift_phone,
            payment_date=reward.shift_to,
            subscription_id=reward.shift_subscription_id,
        )
        try:
            async with async_session_factory() as session:
                repo = SubscriptionRepo(session)
                if response.get("ok"):
                    await repo.shift_next_payment(reward.user_id, reward.shift_to, PRODAMUS_GRACE_DAYS)
                elif not reward.retry:
                    await repo.add_pending_bonus(reward.user_id, reward.days)
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось сохранить перенос списания user=%s", reward.user_id)
        if not response.get("ok"):
            logger.error(
                "Prodamus: не удалось перенести дату списания на %s дн. (user=%s) — повторим при следующем списании",
                reward.days,
                reward.user_id,
            )

    if bot is None or reward.telegram_id is None:
        return
    if reward.expires_at is None:
        text = REFERRAL_REWARD_NOTIFY_LIFETIME
    else:
        text = REFERRAL_REWARD_NOTIFY.format(days=reward.days, expires=_format_date(reward.expires_at))
    try:
        await bot.send_message(reward.telegram_id, text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось уведомить о реферальном бонусе пользователя %s", reward.telegram_id)


# Ссылки на фоновые задачи, чтобы сборщик мусора не прервал их до завершения.
_background_tasks: set[asyncio.Task] = set()


def _run_in_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def handle_notification(request: web.Request) -> web.Response:
    """POST-уведомление Prodamus: проверяет подпись и применяет событие к подписке."""
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    if _rate_limited(ip):
        logger.warning("Prodamus: превышен лимит запросов с %s", ip)
        return web.Response(status=429, text="too many requests")

    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return web.Response(status=413, text="payload too large")

    try:
        pairs = await _read_form_pairs(request)
    except web.HTTPRequestEntityTooLarge:
        return web.Response(status=413, text="payload too large")
    except ValueError:
        logger.warning("Prodamus: не удалось разобрать тело (content-type=%s)", request.content_type)
        return web.Response(status=400, text="bad form")

    data = parse_php_pairs(pairs)
    # Канонический вид тела — для ключа идемпотентности, если в данных мало полей.
    raw = urlencode(pairs)
    signature = request.headers.get("Sign") or request.headers.get("sign")
    if not verify_signature(data, PRODAMUS_SECRET_KEY, signature):
        # В лог — ничего секретного: только ключи payload и обрезанная подпись.
        logger.warning(
            "Prodamus: неверная подпись (order_id=%s, content-type=%s, keys=%s, sign=%s…)",
            data.get("order_id"),
            request.content_type,
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
    # REST-вызовы Prodamus (до 15 с) — в фоне: ответ на вебхук не должен их ждать,
    # иначе Prodamus сочтёт доставку неудачной и повторит её.
    for reward in (result.referral_reward, result.pending_shift):
        if reward is not None:
            _run_in_background(_apply_referral_reward(request.app.get(BOT_KEY), reward))
    return web.Response(status=200, text="OK")


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_webhook_app(bot: Bot | None = None) -> web.Application:
    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app[BOT_KEY] = bot
    app.router.add_post(PRODAMUS_WEBHOOK_PATH, handle_notification)
    app.router.add_get("/healthz", handle_health)
    return app
