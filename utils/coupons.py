"""Voicebot-only coupon validation and discount helpers."""

from __future__ import annotations

PLAN_VOICEBOT = "voicebot"
VOICEBOT_BASE_PRICE_CENTS = 5000

_COUPONS: list[dict] = [
    {
        "code": "FOREVER10VOICEBOT",
        "discountAmount": 1000,
        "appliesTo": [PLAN_VOICEBOT],
        "isActive": True,
    },
]


def _normalize_code(code: str | None) -> str:
    return (code or "").strip().upper()


def _find_coupon(code: str | None) -> dict | None:
    normalized = _normalize_code(code)
    if not normalized:
        return None

    for coupon in _COUPONS:
        if coupon.get("code", "").upper() == normalized:
            return coupon
    return None


def validate_coupon(code: str | None, product: str = PLAN_VOICEBOT) -> bool:
    coupon = _find_coupon(code)
    if not coupon:
        return False

    product_name = (product or "").strip().lower()
    applies_to = [item.strip().lower() for item in coupon.get("appliesTo", [])]
    return bool(coupon.get("isActive")) and product_name in applies_to


def get_discount_amount(code: str | None, product: str = PLAN_VOICEBOT) -> int:
    if not validate_coupon(code, product):
        return 0

    coupon = _find_coupon(code)
    if not coupon:
        return 0

    try:
        return max(int(coupon.get("discountAmount", 0)), 0)
    except (TypeError, ValueError):
        return 0


def get_voicebot_checkout_unit_amount(code: str | None) -> int:
    discount = get_discount_amount(code, PLAN_VOICEBOT)
    adjusted = VOICEBOT_BASE_PRICE_CENTS - discount
    return max(adjusted, 50)
