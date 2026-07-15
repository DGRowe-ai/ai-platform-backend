"""Manage voicebot subscription cancellations."""

from __future__ import annotations

import logging

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import User
from plan_utils import (
    PRODUCT_DUO,
    PRODUCT_VOICEBOT,
    TIER_CHATBOT,
    apply_tier_to_user,
    get_chatbot_price_id,
    user_product_type,
)

logger = logging.getLogger(__name__)


def cancel_voicebot_subscription(db: Session, user: User) -> dict:
    product = user_product_type(user)
    if product not in {PRODUCT_VOICEBOT, PRODUCT_DUO}:
        raise HTTPException(
            status_code=400,
            detail="Your account does not include an active voicebot subscription.",
        )

    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured.")

    if not user.stripe_customer_id:
        user.subscription_active = 0
        user.billing_status = "inactive"
        db.add(user)
        db.commit()
        return {
            "status": "cancelled",
            "plan_type": user.plan_type,
            "product_type": user_product_type(user),
            "tier": getattr(user, "tier", None),
            "message": "Voicebot service cancelled.",
        }

    try:
        subscriptions = stripe.Subscription.list(
            customer=user.stripe_customer_id,
            status="active",
            limit=1,
        )
    except stripe.error.StripeError as exc:
        logger.exception("Unable to load Stripe subscription for user_id=%s", user.id)
        raise HTTPException(status_code=502, detail="Unable to cancel subscription.") from exc

    if not subscriptions.data:
        user.subscription_active = 0
        user.billing_status = "inactive"
        db.add(user)
        db.commit()
        return {
            "status": "cancelled",
            "plan_type": user.plan_type,
            "product_type": user_product_type(user),
            "tier": getattr(user, "tier", None),
            "message": "Voicebot service cancelled.",
        }

    subscription = subscriptions.data[0]
    current_product = user_product_type(user)

    if current_product == PRODUCT_VOICEBOT:
        stripe.Subscription.cancel(subscription.id)
        user.subscription_active = 0
        user.billing_status = "inactive"
        message = "Voicebot service cancelled."
    else:
        if current_product != PRODUCT_DUO:
            raise HTTPException(status_code=400, detail="Unsupported plan for voice cancellation.")

        items = subscription.get("items", {}).get("data") or []
        if not items:
            raise HTTPException(status_code=400, detail="No subscription items found.")

        chatbot_price = get_chatbot_price_id()
        if not chatbot_price:
            raise HTTPException(
                status_code=503,
                detail="Chatbot price is not configured for downgrade.",
            )

        stripe.Subscription.modify(
            subscription.id,
            items=[{"id": items[0]["id"], "price": chatbot_price}],
            proration_behavior="create_prorations",
        )
        apply_tier_to_user(user, TIER_CHATBOT)
        message = "Voicebot removed from your Duo plan. Your chatbot subscription remains active."

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "status": "cancelled",
        "plan_type": user.plan_type,
        "product_type": user_product_type(user),
        "tier": getattr(user, "tier", None),
        "message": message,
    }
