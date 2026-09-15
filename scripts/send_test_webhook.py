"""
Локальная имитация уведомления Prodamus: подписывает payload тем же ключом,
что и продовый бот, и шлёт POST на вебхук.

    uv run python scripts/send_test_webhook.py --order-id 1-abc123

Полезно, чтобы проверить приём, идемпотентность (запустить дважды) и реакцию на
испорченную подпись (--break-signature).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402

from src.config import PRODAMUS_SECRET_KEY, PRODAMUS_WEBHOOK_PATH, PRODAMUS_WEBHOOK_PORT  # noqa: E402
from src.payments.formdata import php_urlencode  # noqa: E402
from src.payments.hmac_sign import create_signature  # noqa: E402


def build_payload(args) -> dict:
    subscription = {
        "id": args.subscription_id,
        "name": "Премиум",
        "active": "1",
        "active_manager": "0" if args.cancel else "1",
        "active_user": "1",
        "cost": args.amount,
        "payment_num": str(args.payment_num),
    }
    if args.next_payment:
        subscription["date_next_payment"] = args.next_payment
    return {
        "date": args.date,
        "order_id": args.order_id,
        "order_num": "1",
        "sum": args.amount,
        "customer_phone": args.phone,
        "customer_email": args.email,
        "customer_extra": f"tg:{args.telegram_id}",
        "payment_type": "Оплата картой",
        "payment_status": args.status,
        "products": [{"name": "Подписка", "price": args.amount, "quantity": "1"}],
        "subscription": subscription,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Отправить тестовое уведомление Prodamus")
    parser.add_argument("--url", default=f"http://127.0.0.1:{PRODAMUS_WEBHOOK_PORT}{PRODAMUS_WEBHOOK_PATH}")
    parser.add_argument("--order-id", required=True, help="order_id из payment_intents")
    parser.add_argument("--telegram-id", type=int, default=0)
    parser.add_argument("--status", default="success")
    parser.add_argument("--payment-num", type=int, default=1)
    parser.add_argument("--amount", default="299.00")
    parser.add_argument("--phone", default="79998887766")
    parser.add_argument("--email", default="user@example.ru")
    parser.add_argument("--subscription-id", default="1")
    parser.add_argument("--date", default="2026-09-07 12:00:00")
    parser.add_argument("--next-payment", default="2026-10-07 12:00:00")
    parser.add_argument("--cancel", action="store_true", help="имитировать отмену автопродления")
    parser.add_argument("--break-signature", action="store_true", help="испортить подпись (ожидаем 400)")
    args = parser.parse_args()

    if not PRODAMUS_SECRET_KEY:
        print("PRODAMUS_SECRET_KEY не задан в .env", file=sys.stderr)
        return 2

    payload = build_payload(args)
    signature = create_signature(payload, PRODAMUS_SECRET_KEY)
    if args.break_signature:
        signature = "0" * 64

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    async with aiohttp.ClientSession() as session:
        async with session.post(
            args.url,
            data=php_urlencode(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Sign": signature},
        ) as response:
            print(f"\nHTTP {response.status}: {await response.text()}")
            return 0 if response.status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
