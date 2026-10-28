"""Minimal async Razorpay client: create orders and verify signatures."""
import hashlib
import hmac

import httpx

from .config import settings

API = "https://api.razorpay.com/v1"


class RazorpayError(RuntimeError):
    pass


async def create_order(amount_paise: int, receipt: str, notes: dict[str, str]) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API}/orders",
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            json={"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes},
        )
    if resp.status_code >= 400:
        raise RazorpayError(f"Razorpay order creation failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    expected = _hmac_hex(settings.razorpay_key_secret, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    # Must be computed over the exact bytes received, never re-serialised JSON.
    if not settings.razorpay_webhook_secret:
        return False
    return hmac.compare_digest(_hmac_hex(settings.razorpay_webhook_secret, raw_body), signature)
