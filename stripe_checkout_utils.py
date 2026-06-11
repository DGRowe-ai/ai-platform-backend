import os
import logging

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from business_utils import get_business_by_key
from models import User

logger = logging.getLogger(__name__)

DEFAULT_BACKEND_URL = "https://ai-platform-backend-ulqs.onrender.com"
DEFAULT_FRONTEND_URL = "https://ai-platform-frontend-uaaa.onrender.com"


def get_backend_public_url() -> str:
    return (
        os.getenv("BACKEND_PUBLIC_URL")
        or os.getenv("PUBLIC_BACKEND_URL")
        or DEFAULT_BACKEND_URL
    ).rstrip("/")


def get_frontend_public_url() -> str:
    return (
        os.getenv("FRONTEND_PUBLIC_URL")
        or os.getenv("PUBLIC_FRONTEND_URL")
        or DEFAULT_FRONTEND_URL
    ).rstrip("/")


def get_stripe_price_id() -> str:
    price_id = (
        os.getenv("STRIPE_PRICE_ID")
        or os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID")
        or os.getenv("STRIPE_PRICE")
    )
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail="Stripe subscription price is not configured",
        )
    return price_id


def build_checkout_activation_url(email: str) -> str:
    from urllib.parse import quote

    normalized_email = (email or "").strip().lower()
    return (
        f"{get_backend_public_url()}/create-checkout-session"
        f"?email={quote(normalized_email)}"
    )


def resolve_checkout_user(
    db: Session,
    *,
    email: str | None = None,
    business_id: str | None = None,
) -> User:
    if email:
        normalized_email = email.strip().lower()
        user = db.query(User).filter(User.email == normalized_email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    if business_id:
        business = get_business_by_key(db, business_id.strip())
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")

        user = db.query(User).filter(User.id == business.owner_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found for business")
        return user

    raise HTTPException(
        status_code=400,
        detail="Provide either email or business_id",
    )


def get_or_create_stripe_customer(db: Session, user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id

    if not stripe.api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured for checkout",
        )

    try:
        customer = stripe.Customer.create(email=user.email)
    except stripe.error.StripeError as exc:
        logger.exception("Stripe customer creation failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=502,
            detail="Unable to create Stripe customer",
        ) from exc

    user.stripe_customer_id = customer.id
    db.add(user)
    db.commit()
    db.refresh(user)
    return customer.id


def create_subscription_checkout_session(db: Session, user: User) -> str:
    customer_id = get_or_create_stripe_customer(db, user)
    frontend_url = get_frontend_public_url()
    price_id = get_stripe_price_id()

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{frontend_url}/client-dashboard.html?checkout=success",
            cancel_url=f"{frontend_url}/client-dashboard.html?checkout=canceled",
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe checkout session failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=502,
            detail="Unable to create Stripe checkout session",
        ) from exc

    if not session.url:
        raise HTTPException(
            status_code=502,
            detail="Stripe checkout session did not return a redirect URL",
        )

    return session.url
