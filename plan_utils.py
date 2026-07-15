"""Subscription plan helpers for chatbot, voicebot tiers, and duo bundles."""

from __future__ import annotations

import os

from fastapi import HTTPException

from models import User

# Product types (dashboard routing)
PRODUCT_CHATBOT = "chatbot"
PRODUCT_VOICEBOT = "voicebot"
PRODUCT_DUO = "duo"

# Tiers
TIER_CHATBOT = "chatbot"
TIER_STARTER = "starter"
TIER_PRO = "pro"
TIER_PREMIUM = "premium"
TIER_DUO_STARTER = "duo_starter"
TIER_DUO_PRO = "duo_pro"
TIER_DUO_PREMIUM = "duo_premium"

VALID_TIERS = {
    TIER_CHATBOT,
    TIER_STARTER,
    TIER_PRO,
    TIER_PREMIUM,
    TIER_DUO_STARTER,
    TIER_DUO_PRO,
    TIER_DUO_PREMIUM,
}

VALID_PRODUCTS = {PRODUCT_CHATBOT, PRODUCT_VOICEBOT, PRODUCT_DUO}

# Legacy plan aliases (deprecated — mapped, never offered in UI/checkout)
LEGACY_PLAN_ALIASES = {
    "voicebot": TIER_STARTER,
    "duo": TIER_DUO_STARTER,
}

TIER_TO_PRODUCT = {
    TIER_CHATBOT: PRODUCT_CHATBOT,
    TIER_STARTER: PRODUCT_VOICEBOT,
    TIER_PRO: PRODUCT_VOICEBOT,
    TIER_PREMIUM: PRODUCT_VOICEBOT,
    TIER_DUO_STARTER: PRODUCT_DUO,
    TIER_DUO_PRO: PRODUCT_DUO,
    TIER_DUO_PREMIUM: PRODUCT_DUO,
}

# Display / checkout prices in cents (no 9's)
TIER_PRICE_CENTS = {
    TIER_CHATBOT: 4000,
    TIER_STARTER: 10000,
    TIER_PRO: 15000,
    TIER_PREMIUM: 20000,
    TIER_DUO_STARTER: 13000,
    TIER_DUO_PRO: 17000,
    TIER_DUO_PREMIUM: 22000,
}

VOICEBOT_FEATURE_TIERS = {TIER_STARTER, TIER_PRO, TIER_PREMIUM}
DUO_TIERS = {TIER_DUO_STARTER, TIER_DUO_PRO, TIER_DUO_PREMIUM}
COUPON_ELIGIBLE_TIERS = VOICEBOT_FEATURE_TIERS | DUO_TIERS
PREMIUM_TIERS = {TIER_PREMIUM, TIER_DUO_PREMIUM}
PRO_OR_HIGHER_VOICE = {TIER_PRO, TIER_PREMIUM, TIER_DUO_PRO, TIER_DUO_PREMIUM}

# Backward-compatible aliases used throughout older modules
PLAN_CHATBOT = PRODUCT_CHATBOT
PLAN_VOICEBOT = PRODUCT_VOICEBOT
PLAN_DUO = PRODUCT_DUO
VALID_PLANS = VALID_PRODUCTS

COMPLIMENTARY_DUO_EMAILS = {
    "rowe-ai@outlook.com",
}

# Backward-compatible alias
COMPLIMENTARY_VOICE_EMAILS = COMPLIMENTARY_DUO_EMAILS


def is_complimentary_account(user: User | None = None, email: str | None = None) -> bool:
    resolved = ""
    if user is not None:
        resolved = (user.email or "").strip().lower()
    elif email:
        resolved = email.strip().lower()
    return resolved in COMPLIMENTARY_DUO_EMAILS


DASHBOARD_BY_PRODUCT = {
    PRODUCT_CHATBOT: "dashboard-chatbot.html",
    PRODUCT_VOICEBOT: "dashboard-voicebot.html",
    PRODUCT_DUO: "dashboard-duo.html",
}


def normalize_tier(value: str | None, default: str = TIER_CHATBOT) -> str:
    raw = (value or default).strip().lower()
    if raw in LEGACY_PLAN_ALIASES:
        return LEGACY_PLAN_ALIASES[raw]
    if raw in VALID_TIERS:
        return raw
    if raw in VALID_PRODUCTS:
        # product-only value → default matching tier
        if raw == PRODUCT_VOICEBOT:
            return TIER_STARTER
        if raw == PRODUCT_DUO:
            return TIER_DUO_STARTER
        return TIER_CHATBOT
    return default


def product_type_from_tier(tier: str | None) -> str:
    normalized = normalize_tier(tier)
    return TIER_TO_PRODUCT.get(normalized, PRODUCT_CHATBOT)


def normalize_plan_type(value: str | None, default: str = PLAN_CHATBOT) -> str:
    """Normalize to product_type for backward compatibility with plan_type fields."""
    raw = (value or "").strip().lower()
    if not raw:
        return default
    if raw in VALID_TIERS:
        return product_type_from_tier(raw)
    if raw in LEGACY_PLAN_ALIASES:
        return product_type_from_tier(LEGACY_PLAN_ALIASES[raw])
    if raw in VALID_PRODUCTS:
        return raw
    return default


def normalize_checkout_plan(value: str | None, default: str = TIER_CHATBOT) -> str:
    """Normalize a checkout request value to a tier id."""
    return normalize_tier(value, default)


def get_voice_capability_tier(tier: str | None) -> str | None:
    """Map duo/voice tiers to the voice feature level: starter|pro|premium."""
    normalized = normalize_tier(tier)
    if normalized == TIER_DUO_STARTER or normalized == TIER_STARTER:
        return TIER_STARTER
    if normalized == TIER_DUO_PRO or normalized == TIER_PRO:
        return TIER_PRO
    if normalized == TIER_DUO_PREMIUM or normalized == TIER_PREMIUM:
        return TIER_PREMIUM
    return None


def tier_allows_multi_location(tier: str | None) -> bool:
    return normalize_tier(tier) in PREMIUM_TIERS


def tier_allows_call_forwarding(tier: str | None) -> bool:
    return normalize_tier(tier) in PRO_OR_HIGHER_VOICE


def tier_allows_custom_personality(tier: str | None) -> bool:
    return normalize_tier(tier) in PRO_OR_HIGHER_VOICE


def tier_allows_follow_ups(tier: str | None) -> bool:
    return normalize_tier(tier) in PRO_OR_HIGHER_VOICE


def tier_is_premium(tier: str | None) -> bool:
    return normalize_tier(tier) in PREMIUM_TIERS


def get_tier_price_cents(tier: str | None) -> int:
    return TIER_PRICE_CENTS.get(normalize_tier(tier), TIER_PRICE_CENTS[TIER_CHATBOT])


def get_chatbot_price_id() -> str:
    return (
        os.getenv("STRIPE_PRICE_CHATBOT")
        or os.getenv("CHATBOT_PRICE_ID")
        or os.getenv("STRIPE_PRICE_ID")
        or os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID")
        or os.getenv("STRIPE_PRICE")
        or ""
    ).strip()


def get_voicebot_starter_price_id() -> str:
    return (os.getenv("STRIPE_PRICE_VOICEBOT_STARTER") or "").strip()


def get_voicebot_pro_price_id() -> str:
    return (os.getenv("STRIPE_PRICE_VOICEBOT_PRO") or "").strip()


def get_voicebot_premium_price_id() -> str:
    return (os.getenv("STRIPE_PRICE_VOICEBOT_PREMIUM") or "").strip()


def get_duo_starter_price_id() -> str:
    return (os.getenv("STRIPE_PRICE_DUO_STARTER") or "").strip()


def get_duo_pro_price_id() -> str:
    return (os.getenv("STRIPE_PRICE_DUO_PRO") or "").strip()


def get_duo_premium_price_id() -> str:
    return (os.getenv("STRIPE_PRICE_DUO_PREMIUM") or "").strip()


def get_voicebot_price_id() -> str:
    """Deprecated single voicebot price — falls back to starter."""
    return (
        os.getenv("VOICEBOT_PRICE_ID")
        or get_voicebot_starter_price_id()
        or ""
    ).strip()


def get_duo_price_id() -> str:
    """Deprecated single duo price — falls back to duo starter."""
    return (
        os.getenv("DUO_PRICE_ID")
        or get_duo_starter_price_id()
        or ""
    ).strip()


_TIER_PRICE_ENV_GETTERS = {
    TIER_CHATBOT: get_chatbot_price_id,
    TIER_STARTER: get_voicebot_starter_price_id,
    TIER_PRO: get_voicebot_pro_price_id,
    TIER_PREMIUM: get_voicebot_premium_price_id,
    TIER_DUO_STARTER: get_duo_starter_price_id,
    TIER_DUO_PRO: get_duo_pro_price_id,
    TIER_DUO_PREMIUM: get_duo_premium_price_id,
}


def get_stripe_price_id_for_plan(plan_type: str) -> str:
    """Resolve Stripe price id for a tier or legacy product type."""
    tier = normalize_checkout_plan(plan_type)
    getter = _TIER_PRICE_ENV_GETTERS.get(tier)
    price_id = getter() if getter else ""

    if not price_id and tier in VOICEBOT_FEATURE_TIERS:
        price_id = get_voicebot_price_id()
    if not price_id and tier in DUO_TIERS:
        price_id = get_duo_price_id()

    if not price_id:
        raise HTTPException(
            status_code=503,
            detail="Stripe subscription price is not configured for this plan",
        )
    return price_id


def plan_type_from_stripe_price(price_id: str | None) -> str | None:
    """Return product_type for a Stripe price id (legacy helper)."""
    tier = tier_from_stripe_price(price_id)
    if not tier:
        return None
    return product_type_from_tier(tier)


def tier_from_stripe_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    normalized = price_id.strip()
    mapping = [
        (get_chatbot_price_id(), TIER_CHATBOT),
        (get_voicebot_starter_price_id(), TIER_STARTER),
        (get_voicebot_pro_price_id(), TIER_PRO),
        (get_voicebot_premium_price_id(), TIER_PREMIUM),
        (get_duo_starter_price_id(), TIER_DUO_STARTER),
        (get_duo_pro_price_id(), TIER_DUO_PRO),
        (get_duo_premium_price_id(), TIER_DUO_PREMIUM),
        # Legacy single-price fallbacks
        (get_voicebot_price_id(), TIER_STARTER),
        (get_duo_price_id(), TIER_DUO_STARTER),
    ]
    for configured, tier in mapping:
        if configured and normalized == configured:
            return tier
    return None


def user_tier(user: User) -> str:
    stored = getattr(user, "tier", None)
    if stored:
        return normalize_tier(stored)
    # Derive from legacy plan_type
    return normalize_tier(getattr(user, "plan_type", None))


def user_product_type(user: User) -> str:
    stored = getattr(user, "product_type", None)
    if stored and stored in VALID_PRODUCTS:
        return stored
    return product_type_from_tier(user_tier(user))


def user_plan_type(user: User) -> str:
    """Backward-compatible product type accessor."""
    return user_product_type(user)


def apply_tier_to_user(user: User, tier: str | None) -> str:
    normalized = normalize_tier(tier)
    user.tier = normalized
    user.product_type = product_type_from_tier(normalized)
    user.plan_type = user.product_type
    return normalized


def user_has_chatbot(user: User) -> bool:
    if user_product_type(user) in {PRODUCT_CHATBOT, PRODUCT_DUO}:
        return True
    return is_complimentary_account(user)


def user_has_voicebot(user: User) -> bool:
    product = user_product_type(user)
    if product in {PRODUCT_VOICEBOT, PRODUCT_DUO}:
        return True
    return is_complimentary_account(user)


def serialize_subscription(user: User) -> dict:
    tier = user_tier(user)
    product = user_product_type(user)
    voice_level = get_voice_capability_tier(tier)
    complimentary = is_complimentary_account(user)
    return {
        "tier": tier,
        "product_type": product,
        "plan_type": product,
        "voice_tier": voice_level,
        "has_chatbot": user_has_chatbot(user),
        "has_voicebot": user_has_voicebot(user),
        "complimentary": complimentary,
        "subscription_active": bool(user.subscription_active),
        "billing_status": user.billing_status or "inactive",
        "dashboard_url": DASHBOARD_BY_PRODUCT.get(product, DASHBOARD_BY_PRODUCT[PRODUCT_CHATBOT]),
        "features": {
            "multi_location": tier_allows_multi_location(tier),
            "call_forwarding": tier_allows_call_forwarding(tier),
            "custom_personality": tier_allows_custom_personality(tier),
            "follow_up_questions": tier_allows_follow_ups(tier),
            "custom_workflows": tier_is_premium(tier),
            "monthly_optimization": tier_is_premium(tier),
            "dedicated_support": tier_is_premium(tier),
        },
    }


def require_chatbot_access(user: User) -> None:
    if not user_has_chatbot(user):
        raise HTTPException(
            status_code=403,
            detail="Your subscription does not include the chatbot dashboard.",
        )


def require_voicebot_access(user: User) -> None:
    if not user_has_voicebot(user):
        raise HTTPException(
            status_code=403,
            detail="Your subscription does not include the voicebot dashboard.",
        )


def require_duo_access(user: User) -> None:
    if user_product_type(user) != PRODUCT_DUO:
        raise HTTPException(
            status_code=403,
            detail="Your subscription does not include the duo dashboard.",
        )


def dashboard_path_for_user(user: User) -> str:
    return DASHBOARD_BY_PRODUCT.get(
        user_product_type(user),
        DASHBOARD_BY_PRODUCT[PRODUCT_CHATBOT],
    )
