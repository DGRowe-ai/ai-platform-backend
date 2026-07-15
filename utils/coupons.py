"""Founders coupon validation — $10 off permanently for voicebot and duo tiers only."""

from __future__ import annotations

from plan_utils import (
    COUPON_ELIGIBLE_TIERS,
    TIER_PRICE_CENTS,
    normalize_checkout_plan,
)

FOUNDERS_COUPON_CODE = "FOUNDERS10"
FOUNDERS_DISCOUNT_CENTS = 1000

# Deprecated chatbot-only coupons — intentionally not registered
_DEPRECATED_COUPON_CODES = {
    "CHATBOT10",
    "FOREVER10CHATBOT",
    "FOUNDERSCHATBOT",
}

_COUPONS: list[dict] = [
    {
        "code": FOUNDERS_COUPON_CODE,
        "discountAmount": FOUNDERS_DISCOUNT_CENTS,
        "appliesTo": sorted(COUPON_ELIGIBLE_TIERS),
        "isActive": True,
    },
    # Keep old voicebot code as an alias that maps to the same founders discount
    {
        "code": "FOREVER10VOICEBOT",
        "discountAmount": FOUNDERS_DISCOUNT_CENTS,
        "appliesTo": sorted(COUPON_ELIGIBLE_TIERS),
        "isActive": True,
    },
]


def _normalize_code(code: str | None) -> str:
    return (code or "").strip().upper()


def _find_coupon(code: str | None) -> dict | None:
    normalized = _normalize_code(code)
    if not normalized:
        return None
    if normalized in _DEPRECATED_COUPON_CODES:
        return None

    for coupon in _COUPONS:
        if coupon.get("code", "").upper() == normalized:
            return coupon
    return None


def validate_coupon(code: str | None, product: str | None = None) -> bool:
    """Validate coupon for a tier (starter/pro/premium/duo_*) or product type."""
    coupon = _find_coupon(code)
    if not coupon or not coupon.get("isActive"):
        return False

    tier = normalize_checkout_plan(product)
    applies_to = {item.strip().lower() for item in coupon.get("appliesTo", [])}
    return tier in applies_to and tier in COUPON_ELIGIBLE_TIERS


def get_discount_amount(code: str | None, product: str | None = None) -> int:
    if not validate_coupon(code, product):
        return 0

    coupon = _find_coupon(code)
    if not coupon:
        return 0

    try:
        return max(int(coupon.get("discountAmount", 0)), 0)
    except (TypeError, ValueError):
        return 0


def get_checkout_unit_amount(tier: str | None, code: str | None = None) -> int:
    normalized = normalize_checkout_plan(tier)
    base = TIER_PRICE_CENTS.get(normalized, TIER_PRICE_CENTS["chatbot"])
    discount = get_discount_amount(code, normalized)
    return max(base - discount, 50)


# Backward-compatible aliases used by older checkout code
VOICEBOT_BASE_PRICE_CENTS = TIER_PRICE_CENTS["starter"]


def get_voicebot_checkout_unit_amount(code: str | None) -> int:
    return get_checkout_unit_amount("starter", code)
