"""Free-trial abuse prevention: one trial per identity signal."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth_utils import normalize_email
from models import TrialEnrollment

logger = logging.getLogger(__name__)

TRIAL_IP_MAX_COUNT = 3
TRIAL_IP_REPEAT_HOURS = 24


@dataclass
class TrialEligibilityResult:
    eligible: bool
    reason: str | None = None


def phone_digits_for_trial(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value.strip())
    return digits or None


def normalize_device_fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32,128}", cleaned):
        return None
    return cleaned


def get_client_ip(request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _trial_ip_window_hours() -> int:
    raw = os.getenv("TRIAL_IP_REPEAT_HOURS", str(TRIAL_IP_REPEAT_HOURS))
    try:
        return max(int(raw), 1)
    except ValueError:
        return TRIAL_IP_REPEAT_HOURS


def _trial_ip_max_count() -> int:
    raw = os.getenv("TRIAL_IP_MAX_COUNT", str(TRIAL_IP_MAX_COUNT))
    try:
        return max(int(raw), 1)
    except ValueError:
        return TRIAL_IP_MAX_COUNT


def _identifier_query(db: Session, column, value: str):
    if value is None:
        return None
    return (
        db.query(TrialEnrollment)
        .filter(column == value, TrialEnrollment.trial_used == 1)
        .first()
    )


def check_trial_eligibility(
    db: Session,
    *,
    email: str | None = None,
    phone: str | None = None,
    stripe_customer_id: str | None = None,
    card_fingerprint: str | None = None,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
) -> TrialEligibilityResult:
    normalized_email = normalize_email(email) if email else None
    normalized_phone = phone_digits_for_trial(phone)
    normalized_device = normalize_device_fingerprint(device_fingerprint)
    normalized_ip = (ip_address or "").strip() or None

    if normalized_email and _identifier_query(db, TrialEnrollment.email, normalized_email):
        return TrialEligibilityResult(False, "A free trial has already been used for this email address.")

    if normalized_phone and _identifier_query(db, TrialEnrollment.phone, normalized_phone):
        return TrialEligibilityResult(False, "A free trial has already been used for this phone number.")

    if stripe_customer_id and _identifier_query(
        db, TrialEnrollment.stripe_customer_id, stripe_customer_id
    ):
        return TrialEligibilityResult(False, "A free trial has already been used for this billing account.")

    if card_fingerprint and _identifier_query(
        db, TrialEnrollment.card_fingerprint, card_fingerprint
    ):
        return TrialEligibilityResult(False, "A free trial has already been used for this payment method.")

    if normalized_device and _identifier_query(
        db, TrialEnrollment.device_fingerprint, normalized_device
    ):
        return TrialEligibilityResult(False, "A free trial has already been used on this device.")

    if normalized_ip:
        ip_count = (
            db.query(TrialEnrollment)
            .filter(
                TrialEnrollment.ip_address == normalized_ip,
                TrialEnrollment.trial_used == 1,
            )
            .count()
        )
        if ip_count >= _trial_ip_max_count():
            return TrialEligibilityResult(
                False,
                "Too many free trials have been started from this network.",
            )

        repeat_cutoff = datetime.utcnow() - timedelta(hours=_trial_ip_window_hours())
        recent_ip = (
            db.query(TrialEnrollment)
            .filter(
                TrialEnrollment.ip_address == normalized_ip,
                TrialEnrollment.trial_used == 1,
                TrialEnrollment.created_at >= repeat_cutoff,
            )
            .first()
        )
        if recent_ip:
            return TrialEligibilityResult(
                False,
                "A free trial was recently started from this network. Please subscribe without a trial.",
            )

    return TrialEligibilityResult(True, None)


def record_trial_enrollment(
    db: Session,
    *,
    email: str | None = None,
    phone: str | None = None,
    stripe_customer_id: str | None = None,
    card_fingerprint: str | None = None,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
    stripe_session_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> TrialEnrollment:
    """Persist trial usage permanently (survives account deletion)."""
    from sqlalchemy import or_

    normalized_email = normalize_email(email) if email else None
    normalized_phone = phone_digits_for_trial(phone)
    normalized_device = normalize_device_fingerprint(device_fingerprint)
    normalized_ip = (ip_address or "").strip() or None

    filters = []
    if normalized_email:
        filters.append(TrialEnrollment.email == normalized_email)
    if stripe_customer_id:
        filters.append(TrialEnrollment.stripe_customer_id == stripe_customer_id)
    if stripe_session_id:
        filters.append(TrialEnrollment.stripe_session_id == stripe_session_id)

    existing = None
    if filters:
        existing = (
            db.query(TrialEnrollment)
            .filter(TrialEnrollment.trial_used == 1, or_(*filters))
            .first()
        )

    if existing:
        if normalized_phone and not existing.phone:
            existing.phone = normalized_phone
        if stripe_customer_id and not existing.stripe_customer_id:
            existing.stripe_customer_id = stripe_customer_id
        if card_fingerprint and not existing.card_fingerprint:
            existing.card_fingerprint = card_fingerprint
        if normalized_device and not existing.device_fingerprint:
            existing.device_fingerprint = normalized_device
        if normalized_ip and not existing.ip_address:
            existing.ip_address = normalized_ip
        if stripe_subscription_id and not existing.stripe_subscription_id:
            existing.stripe_subscription_id = stripe_subscription_id
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    record = TrialEnrollment(
        email=normalized_email,
        phone=normalized_phone,
        stripe_customer_id=stripe_customer_id or None,
        card_fingerprint=card_fingerprint or None,
        device_fingerprint=normalized_device,
        ip_address=normalized_ip,
        stripe_session_id=stripe_session_id or None,
        stripe_subscription_id=stripe_subscription_id or None,
        trial_used=1,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def persist_trial_identifiers_on_account_deletion(
    db: Session,
    *,
    email: str,
    phone: str | None,
    stripe_customer_id: str | None,
) -> None:
    """Ensure trial flags remain after the user deletes their account."""
    from sqlalchemy import or_

    normalized_email = normalize_email(email)
    normalized_phone = phone_digits_for_trial(phone)

    filters = [TrialEnrollment.email == normalized_email]
    if stripe_customer_id:
        filters.append(TrialEnrollment.stripe_customer_id == stripe_customer_id)

    existing = (
        db.query(TrialEnrollment)
        .filter(TrialEnrollment.trial_used == 1, or_(*filters))
        .first()
    )
    if existing:
        updated = False
        if normalized_phone and not existing.phone:
            existing.phone = normalized_phone
            updated = True
        if stripe_customer_id and not existing.stripe_customer_id:
            existing.stripe_customer_id = stripe_customer_id
            updated = True
        if updated:
            db.add(existing)
            db.commit()
        return

    record_trial_enrollment(
        db,
        email=normalized_email,
        phone=normalized_phone,
        stripe_customer_id=stripe_customer_id,
    )


def extract_card_fingerprint_from_session(session: dict) -> str | None:
    if not stripe.api_key:
        return None

    subscription_id = session.get("subscription")
    if not subscription_id:
        return None

    try:
        subscription = stripe.Subscription.retrieve(
            subscription_id,
            expand=["default_payment_method"],
        )
    except stripe.error.StripeError:
        logger.exception("Unable to retrieve subscription=%s for card fingerprint", subscription_id)
        return None

    payment_method = subscription.get("default_payment_method")
    if isinstance(payment_method, str):
        try:
            payment_method = stripe.PaymentMethod.retrieve(payment_method)
        except stripe.error.StripeError:
            logger.exception("Unable to retrieve payment method for subscription=%s", subscription_id)
            return None

    if not payment_method:
        return None

    card = payment_method.get("card") or {}
    return card.get("fingerprint")


def strip_subscription_trial(subscription_id: str | None) -> bool:
    if not subscription_id or not stripe.api_key:
        return False

    try:
        stripe.Subscription.modify(subscription_id, trial_end="now")
        logger.info("Removed trial from subscription=%s", subscription_id)
        return True
    except stripe.error.StripeError:
        logger.exception("Failed to remove trial from subscription=%s", subscription_id)
        return False


def enforce_trial_or_raise(result: TrialEligibilityResult) -> None:
    if not result.eligible:
        raise HTTPException(
            status_code=403,
            detail=result.reason or "Free trial is not available. Please subscribe without a trial.",
        )


def process_checkout_trial_protection(
    db: Session,
    session: dict,
    *,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
) -> TrialEligibilityResult:
    """Run full trial checks after Stripe checkout completes."""
    details = session.get("customer_details") or {}
    email = details.get("email") or session.get("customer_email")
    stripe_customer_id = session.get("customer")
    card_fingerprint = extract_card_fingerprint_from_session(session)
    metadata = session.get("metadata") or {}
    device_from_metadata = metadata.get("device_fingerprint") or device_fingerprint
    ip_from_metadata = metadata.get("signup_ip") or ip_address

    result = check_trial_eligibility(
        db,
        email=email,
        stripe_customer_id=stripe_customer_id,
        card_fingerprint=card_fingerprint,
        device_fingerprint=device_from_metadata,
        ip_address=ip_from_metadata,
    )

    if not result.eligible:
        strip_subscription_trial(session.get("subscription"))
        return result

    record_trial_enrollment(
        db,
        email=email,
        stripe_customer_id=stripe_customer_id,
        card_fingerprint=card_fingerprint,
        device_fingerprint=device_from_metadata,
        ip_address=ip_from_metadata,
        stripe_session_id=session.get("id"),
        stripe_subscription_id=session.get("subscription"),
    )
    return result
