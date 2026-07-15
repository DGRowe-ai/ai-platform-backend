import os
import logging
from datetime import datetime

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth_utils import normalize_email
from business_utils import get_business_by_key
from models import BillingCheckoutSession, User
from plan_utils import (
    COUPON_ELIGIBLE_TIERS,
    PLAN_CHATBOT,
    TIER_CHATBOT,
    apply_tier_to_user,
    get_stripe_price_id_for_plan,
    get_tier_price_cents,
    normalize_checkout_plan,
    normalize_plan_type,
    product_type_from_tier,
    tier_from_stripe_price,
)
from utils.coupons import (
    get_checkout_unit_amount,
    get_discount_amount,
    validate_coupon,
)
from trial_protection_utils import check_trial_eligibility

logger = logging.getLogger(__name__)

DEFAULT_BACKEND_URL = "https://ai-platform-backend-ulqs.onrender.com"
DEFAULT_FRONTEND_URL = "https://ai-platform-frontend-uaaa.onrender.com"

TIER_PRODUCT_LABELS = {
    "chatbot": "Rowe AI Chatbot Subscription",
    "starter": "Rowe AI Voicebot Starter",
    "pro": "Rowe AI Voicebot Pro",
    "premium": "Rowe AI Voicebot Premium",
    "duo_starter": "Rowe AI Duo Starter",
    "duo_pro": "Rowe AI Duo Pro",
    "duo_premium": "Rowe AI Duo Premium",
}


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
    """Backward-compatible default chatbot price lookup."""
    return get_stripe_price_id_for_plan(TIER_CHATBOT)


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


def _apply_tier_to_checkout_record(record: BillingCheckoutSession, tier: str) -> None:
    normalized = normalize_checkout_plan(tier)
    record.tier = normalized
    record.product_type = product_type_from_tier(normalized)
    record.plan_type = record.product_type


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
    metadata = session.get("metadata") or {}
    referral_code = metadata.get("referral_code")
    if referral_code:
        record.referral_code = referral_code.strip()

    tier_value = metadata.get("tier") or metadata.get("plan_type")
    if tier_value:
        _apply_tier_to_checkout_record(record, tier_value)

    coupon_code = metadata.get("coupon_code")
    if coupon_code:
        record.coupon_code = coupon_code.strip().upper()
    elif session.get("subscription") and not record.tier:
        try:
            subscription = stripe.Subscription.retrieve(session.get("subscription"))
            items = (subscription.get("items") or {}).get("data") or []
            if items:
                price_id = items[0].get("price", {}).get("id")
                resolved = tier_from_stripe_price(price_id)
                if resolved:
                    _apply_tier_to_checkout_record(record, resolved)
        except stripe.error.StripeError:
            logger.warning("Unable to resolve tier from checkout subscription")
    if not record.created_at:
        record.created_at = datetime.utcnow()

    db.commit()
    db.refresh(record)
    return record


def _discounted_line_items(tier: str, coupon_code: str) -> list[dict]:
    currency = (os.getenv("STRIPE_CURRENCY") or os.getenv("VOICEBOT_CURRENCY") or "cad").strip().lower()
    unit_amount = get_checkout_unit_amount(tier, coupon_code)
    label = TIER_PRODUCT_LABELS.get(tier, "Rowe AI Subscription")
    return [
        {
            "price_data": {
                "currency": currency,
                "product_data": {"name": label},
                "unit_amount": unit_amount,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }
    ]


def _resolve_checkout_line_items(plan_type: str, coupon_code: str | None) -> tuple[list[dict], str | None, str]:
    resolved_tier = normalize_checkout_plan(plan_type)
    applied_coupon = None

    if (
        coupon_code
        and resolved_tier in COUPON_ELIGIBLE_TIERS
        and validate_coupon(coupon_code, resolved_tier)
    ):
        applied_coupon = coupon_code.strip().upper()
        return _discounted_line_items(resolved_tier, applied_coupon), applied_coupon, resolved_tier

    price_id = get_stripe_price_id_for_plan(resolved_tier)
    return [{"price": price_id, "quantity": 1}], applied_coupon, resolved_tier


def create_billing_first_checkout_session(
    db: Session,
    *,
    referral_code: str | None = None,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
    plan_type: str | None = TIER_CHATBOT,
    coupon_code: str | None = None,
) -> dict:
    if not stripe.api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured for checkout",
        )

    trial_result = check_trial_eligibility(
        db,
        device_fingerprint=device_fingerprint,
        ip_address=ip_address,
    )
    trial_eligible = trial_result.eligible

    frontend_url = get_frontend_public_url()
    line_items, applied_coupon, resolved_tier = _resolve_checkout_line_items(plan_type, coupon_code)
    product_type = product_type_from_tier(resolved_tier)
    trial_days = get_trial_period_days() if trial_eligible else 0

    metadata = {
        "tier": resolved_tier,
        "product_type": product_type,
        "plan_type": resolved_tier,
    }
    if applied_coupon:
        metadata["coupon_code"] = applied_coupon
        metadata["base_price_cents"] = str(get_tier_price_cents(resolved_tier))
        metadata["discount_cents"] = str(get_discount_amount(applied_coupon, resolved_tier))
    if referral_code:
        metadata["referral_code"] = referral_code.strip()
    if device_fingerprint:
        metadata["device_fingerprint"] = device_fingerprint.strip()
    if ip_address:
        metadata["signup_ip"] = ip_address.strip()
    metadata["trial_eligible"] = "1" if trial_eligible else "0"

    subscription_data = {}
    if trial_days > 0:
        subscription_data["trial_period_days"] = trial_days

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=line_items,
            subscription_data=subscription_data or None,
            metadata=metadata or None,
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

    response = {
        "url": session.url,
        "session_id": session.id,
        "tier": resolved_tier,
        "product_type": product_type,
    }
    if applied_coupon:
        response["coupon_applied"] = applied_coupon
        response["adjusted_price_cents"] = get_checkout_unit_amount(resolved_tier, applied_coupon)
    if not trial_eligible:
        response["trial_eligible"] = False
        response["trial_message"] = (
            trial_result.reason
            or "Free trial is not available. You can still subscribe and start immediately."
        )
    else:
        response["trial_eligible"] = True
    return response


def create_subscription_checkout_session(
    db: Session,
    user: User,
    *,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
) -> str:
    customer_id = get_or_create_stripe_customer(db, user)
    frontend_url = get_frontend_public_url()
    price_id = get_stripe_price_id()

    trial_result = check_trial_eligibility(
        db,
        email=user.email,
        stripe_customer_id=customer_id,
        device_fingerprint=device_fingerprint,
        ip_address=ip_address,
    )
    trial_days = get_trial_period_days() if trial_result.eligible else 0

    metadata = {
        "trial_eligible": "1" if trial_result.eligible else "0",
        "tier": TIER_CHATBOT,
        "product_type": PLAN_CHATBOT,
        "plan_type": TIER_CHATBOT,
    }
    if device_fingerprint:
        metadata["device_fingerprint"] = device_fingerprint.strip()
    if ip_address:
        metadata["signup_ip"] = ip_address.strip()

    subscription_data = {}
    if trial_days > 0:
        subscription_data["trial_period_days"] = trial_days

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data=subscription_data or None,
            metadata=metadata,
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
            "tier": getattr(record, "tier", None) or normalize_checkout_plan(record.plan_type),
            "product_type": getattr(record, "product_type", None) or normalize_plan_type(record.plan_type),
        }

    session = retrieve_checkout_session(session_id)
    if session.get("status") != "complete":
        return {"valid": False, "reason": "Checkout not completed"}

    upsert_billing_checkout_session(db, session)
    email = _extract_checkout_email(session)
    metadata = session.get("metadata") or {}
    return {
        "valid": True,
        "email": email,
        "session_id": session_id,
        "tier": metadata.get("tier") or normalize_checkout_plan(metadata.get("plan_type")),
        "product_type": metadata.get("product_type")
        or product_type_from_tier(metadata.get("tier") or metadata.get("plan_type")),
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
    product = normalize_plan_type(getattr(user, "product_type", None) or user.plan_type)
    if product == "duo":
        return_path = "dashboard-duo.html"
    elif product == "voicebot":
        return_path = "dashboard-voicebot.html"
    else:
        return_path = "dashboard-chatbot.html"

    try:
        session = stripe.billingPortal.sessions.create(
            customer=customer_id,
            return_url=f"{frontend_url}/{return_path}",
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


def assign_tier_from_checkout_metadata(user: User, metadata: dict | None, price_id: str | None = None) -> str:
    metadata = metadata or {}
    tier_value = metadata.get("tier") or metadata.get("plan_type")
    if not tier_value and price_id:
        tier_value = tier_from_stripe_price(price_id)
    return apply_tier_to_user(user, tier_value or TIER_CHATBOT)
