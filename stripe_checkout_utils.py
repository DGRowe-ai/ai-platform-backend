import os
import logging
from datetime import datetime

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth_utils import normalize_email
from business_utils import get_business_by_key
from models import BillingCheckoutSession, User

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


def get_trial_period_days() -> int:
    raw = os.getenv("STRIPE_TRIAL_DAYS", "30")
    try:
        return max(int(raw), 0)
    except ValueError:
        return 30


def build_checkout_activation_url(email: str) -> str:
    frontend_url = get_frontend_public_url()
    return f"{frontend_url}/billing.html"


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


def _extract_checkout_email(session: dict) -> str | None:
    details = session.get("customer_details") or {}
    email = details.get("email") or session.get("customer_email")
    if email:
        return normalize_email(email)
    return None


def upsert_billing_checkout_session(db: Session, session: dict) -> BillingCheckoutSession:
    session_id = session.get("id")
    if not session_id:
        raise ValueError("Stripe session id missing")

    record = (
        db.query(BillingCheckoutSession)
        .filter(BillingCheckoutSession.stripe_session_id == session_id)
        .first()
    )
    if not record:
        record = BillingCheckoutSession(stripe_session_id=session_id)
        db.add(record)

    record.stripe_customer_id = session.get("customer") or record.stripe_customer_id
    record.stripe_subscription_id = session.get("subscription") or record.stripe_subscription_id
    record.customer_email = _extract_checkout_email(session) or record.customer_email
    record.billing_status = "active"
    if not record.created_at:
        record.created_at = datetime.utcnow()

    db.commit()
    db.refresh(record)
    return record


def create_billing_first_checkout_session() -> dict:
    if not stripe.api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured for checkout",
        )

    frontend_url = get_frontend_public_url()
    price_id = get_stripe_price_id()
    trial_days = get_trial_period_days()

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={"trial_period_days": trial_days},
            success_url=f"{frontend_url}/register.html?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/billing.html",
        )
    except stripe.error.StripeError as exc:
        logger.exception("Billing-first checkout session failed")
        raise HTTPException(
            status_code=502,
            detail="Unable to create Stripe checkout session",
        ) from exc

    if not session.url:
        raise HTTPException(
            status_code=502,
            detail="Stripe checkout session did not return a redirect URL",
        )

    return {"url": session.url, "session_id": session.id}


def create_subscription_checkout_session(db: Session, user: User) -> str:
    customer_id = get_or_create_stripe_customer(db, user)
    frontend_url = get_frontend_public_url()
    price_id = get_stripe_price_id()
    trial_days = get_trial_period_days()

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={"trial_period_days": trial_days},
            success_url=f"{frontend_url}/register.html?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/billing.html",
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


def retrieve_checkout_session(session_id: str) -> dict:
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    try:
        return stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as exc:
        logger.exception("Unable to retrieve checkout session=%s", session_id)
        raise HTTPException(status_code=400, detail="Invalid checkout session") from exc


def verify_checkout_session_for_registration(db: Session, session_id: str) -> dict:
    record = (
        db.query(BillingCheckoutSession)
        .filter(BillingCheckoutSession.stripe_session_id == session_id)
        .first()
    )

    if record and record.used:
        return {"valid": False, "reason": "Checkout session already used"}

    if record and record.billing_status == "active":
        return {
            "valid": True,
            "email": record.customer_email,
            "session_id": session_id,
        }

    session = retrieve_checkout_session(session_id)
    if session.get("status") != "complete":
        return {"valid": False, "reason": "Checkout not completed"}

    upsert_billing_checkout_session(db, session)
    email = _extract_checkout_email(session)
    return {
        "valid": True,
        "email": email,
        "session_id": session_id,
    }


def consume_checkout_session_for_signup(
    db: Session,
    session_id: str,
    signup_email: str,
) -> BillingCheckoutSession:
    verification = verify_checkout_session_for_registration(db, session_id)
    if not verification.get("valid"):
        raise HTTPException(
            status_code=402,
            detail="Billing must be completed before registration. Start at billing.html.",
        )

    record = (
        db.query(BillingCheckoutSession)
        .filter(BillingCheckoutSession.stripe_session_id == session_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=400, detail="Checkout session not found")

    if record.used:
        raise HTTPException(status_code=400, detail="Checkout session already used")

    normalized_signup_email = normalize_email(signup_email)
    if record.customer_email and record.customer_email != normalized_signup_email:
        raise HTTPException(
            status_code=400,
            detail="Registration email must match the email used during billing checkout",
        )

    if not record.customer_email:
        record.customer_email = normalized_signup_email

    record.used = 1
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def create_customer_portal_session(db: Session, user: User) -> str:
    if not stripe.api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured for billing portal",
        )

    customer_id = get_or_create_stripe_customer(db, user)
    frontend_url = get_frontend_public_url()

    try:
        session = stripe.billingPortal.sessions.create(
            customer=customer_id,
            return_url=f"{frontend_url}/client-dashboard.html",
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe portal session failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=502,
            detail="Unable to create Stripe billing portal session",
        ) from exc

    if not session.url:
        raise HTTPException(
            status_code=502,
            detail="Stripe billing portal did not return a redirect URL",
        )

    return session.url
