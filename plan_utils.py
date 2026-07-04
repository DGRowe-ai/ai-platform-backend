"""Subscription plan helpers for chatbot, voicebot, and duo products."""

from __future__ import annotations

import os

from fastapi import HTTPException

from models import User

PLAN_CHATBOT = "chatbot"
PLAN_VOICEBOT = "voicebot"
PLAN_DUO = "duo"

VALID_PLANS = {PLAN_CHATBOT, PLAN_VOICEBOT, PLAN_DUO}

COMPLIMENTARY_VOICE_EMAILS = {
    "rowe-ai@outlook.com",
}


def normalize_plan_type(value: str | None, default: str = PLAN_CHATBOT) -> str:
    plan = (value or default).strip().lower()
    if plan not in VALID_PLANS:
        return default
    return plan


def get_chatbot_price_id() -> str:
    return (
        os.getenv("CHATBOT_PRICE_ID")
        or os.getenv("STRIPE_PRICE_ID")
        or os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID")
        or os.getenv("STRIPE_PRICE")
        or ""
    ).strip()


def get_voicebot_price_id() -> str:
    return (
        os.getenv("VOICEBOT_PRICE_ID")
        or "price_1TpNMCRo5NdbY54LcJzmh9LB"
    ).strip()


def get_duo_price_id() -> str:
    return (
        os.getenv("DUO_PRICE_ID")
        or "price_1TpNIJRo5NdbY54LJggPE9uZ"
    ).strip()


def get_stripe_price_id_for_plan(plan_type: str) -> str:
    plan = normalize_plan_type(plan_type)
    if plan == PLAN_VOICEBOT:
        price_id = get_voicebot_price_id()
    elif plan == PLAN_DUO:
        price_id = get_duo_price_id()
    else:
        price_id = get_chatbot_price_id()

    if not price_id:
        raise HTTPException(
            status_code=503,
            detail="Stripe subscription price is not configured for this plan",
        )
    return price_id


def plan_type_from_stripe_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    normalized = price_id.strip()
    if normalized == get_voicebot_price_id():
        return PLAN_VOICEBOT
    if normalized == get_duo_price_id():
        return PLAN_DUO
    if normalized == get_chatbot_price_id():
        return PLAN_CHATBOT
    return None


def user_plan_type(user: User) -> str:
    return normalize_plan_type(getattr(user, "plan_type", None))


def user_has_chatbot(user: User) -> bool:
    plan = user_plan_type(user)
    return plan in {PLAN_CHATBOT, PLAN_DUO}


def user_has_voicebot(user: User) -> bool:
    plan = user_plan_type(user)
    if plan in {PLAN_VOICEBOT, PLAN_DUO}:
        return True
    email = (user.email or "").strip().lower()
    return email in COMPLIMENTARY_VOICE_EMAILS


def serialize_subscription(user: User) -> dict:
    plan = user_plan_type(user)
    return {
        "plan_type": plan,
        "has_chatbot": user_has_chatbot(user),
        "has_voicebot": user_has_voicebot(user),
        "subscription_active": bool(user.subscription_active),
        "billing_status": user.billing_status or "inactive",
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
