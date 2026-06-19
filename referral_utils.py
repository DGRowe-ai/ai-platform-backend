"""Referral program utilities for Rowe AI."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth_utils import normalize_email
from models import Business, ReferralSignupLog, User

logger = logging.getLogger(__name__)

REFERRAL_REWARD_DAYS = int(os.getenv("REFERRAL_REWARD_DAYS", "30"))
REFERRAL_IP_WINDOW_HOURS = int(os.getenv("REFERRAL_IP_WINDOW_HOURS", "24"))
REFERRAL_IP_MAX_SIGNUPS = int(os.getenv("REFERRAL_IP_MAX_SIGNUPS", "3"))


def build_referral_link(referral_code: str) -> str:
    base = os.getenv("REFERRAL_BASE_URL", "https://roweai.ca/register?ref=")
    if base.endswith("="):
        return f"{base}{referral_code}"
    if "?" in base:
        joiner = "&" if "ref=" in base or base.endswith("ref") else ("&" if "?" in base else "?")
        if base.endswith("ref"):
            return f"{base}={referral_code}"
        return f"{base}{'&' if '?' in base else '?'}ref={referral_code}"
    return f"{base}?ref={referral_code}"


def generate_unique_referral_code(db: Session) -> str:
    for _ in range(12):
        code = secrets.token_urlsafe(8)
        exists = db.query(User).filter(User.referral_code == code).first()
        if not exists:
            return code
    raise HTTPException(status_code=500, detail="Unable to generate referral code")


def ensure_user_referral_code(db: Session, user: User) -> str:
    if user.referral_code:
        return user.referral_code

    user.referral_code = generate_unique_referral_code(db)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.referral_code


def get_referrer_by_code(db: Session, referral_code: str | None) -> User | None:
    if not referral_code:
        return None

    code = referral_code.strip()
    if not code:
        return None

    return db.query(User).filter(User.referral_code == code).first()


def _recent_referral_signups_for_ip(db: Session, ip_address: str) -> int:
    if not ip_address:
        return 0

    since = datetime.utcnow() - timedelta(hours=REFERRAL_IP_WINDOW_HOURS)
    return (
        db.query(ReferralSignupLog)
        .filter(
            ReferralSignupLog.ip_address == ip_address,
            ReferralSignupLog.created_at >= since,
        )
        .count()
    )


def apply_referral_on_signup(
    db: Session,
    *,
    new_user: User,
    referral_code: str | None,
    signup_ip: str | None = None,
) -> User | None:
    referrer = get_referrer_by_code(db, referral_code)
    if not referrer:
        return None

    if referrer.id == new_user.id:
        logger.warning("Blocked self-referral for user_id=%s", new_user.id)
        return None

    if normalize_email(referrer.email) == normalize_email(new_user.email):
        logger.warning("Blocked same-email referral for user_id=%s", new_user.id)
        return None

    if signup_ip and _recent_referral_signups_for_ip(db, signup_ip) >= REFERRAL_IP_MAX_SIGNUPS:
        logger.warning("Blocked referral signup due to IP rate limit ip=%s", signup_ip)
        return None

    new_user.referred_by_user_id = referrer.id
    db.add(new_user)

    if signup_ip and referral_code:
        db.add(
            ReferralSignupLog(
                ip_address=signup_ip,
                referral_code=referral_code.strip(),
                referred_user_id=new_user.id,
                referrer_user_id=referrer.id,
            )
        )

    return referrer


def extend_referrer_subscription(referrer: User) -> datetime | None:
    if not stripe.api_key:
        logger.warning("Stripe not configured; cannot extend referrer subscription")
        return None

    if not referrer.stripe_customer_id:
        logger.warning(
            "Referrer user_id=%s has no stripe_customer_id; skipping extension",
            referrer.id,
        )
        return None

    subscriptions = stripe.Subscription.list(
        customer=referrer.stripe_customer_id,
        status="all",
        limit=5,
    )
    active_sub = None
    for sub in subscriptions.data:
        if sub.status in {"active", "trialing"}:
            active_sub = sub
            break

    if not active_sub:
        logger.warning(
            "No active Stripe subscription found for referrer user_id=%s",
            referrer.id,
        )
        return None

    current_period_end = int(active_sub.current_period_end)
    new_trial_end = current_period_end + (REFERRAL_REWARD_DAYS * 86400)

    updated = stripe.Subscription.modify(
        active_sub.id,
        trial_end=new_trial_end,
        proration_behavior="none",
    )

    return datetime.utcfromtimestamp(int(updated.current_period_end))


def get_referrer_display_name(db: Session, referrer: User) -> str:
    business = (
        db.query(Business)
        .filter(Business.owner_id == referrer.id)
        .order_by(Business.id.asc())
        .first()
    )
    if business and business.name:
        return business.name
    return referrer.email


def process_referral_conversion(
    db: Session,
    referred_user: User,
    *,
    invoice_id: str | None = None,
) -> dict | None:
    if referred_user.referral_conversion_rewarded:
        return None

    if not referred_user.referred_by_user_id:
        return None

    referrer = db.query(User).filter(User.id == referred_user.referred_by_user_id).first()
    if not referrer:
        return None

    if referrer.id == referred_user.id:
        return None

    referred_user.referral_conversion_rewarded = 1
    referrer.referral_count = int(referrer.referral_count or 0) + 1
    referrer.free_months_earned = int(referrer.free_months_earned or 0) + 1

    updated_renewal = extend_referrer_subscription(referrer)

    db.add(referred_user)
    db.add(referrer)
    db.commit()
    db.refresh(referrer)
    db.refresh(referred_user)

    referrer_name = get_referrer_display_name(db, referrer)
    referred_name = get_referrer_display_name(db, referred_user)

    return {
        "referrer": referrer,
        "referred_user": referred_user,
        "referrer_name": referrer_name,
        "referred_name": referred_name,
        "updated_renewal": updated_renewal,
        "invoice_id": invoice_id,
    }


def get_referral_stats(db: Session, user: User) -> dict:
    code = ensure_user_referral_code(db, user)
    return {
        "referralCode": code,
        "referralLink": build_referral_link(code),
        "successfulReferrals": int(user.referral_count or 0),
        "freeMonthsEarned": int(user.free_months_earned or 0),
        "rewardDaysPerReferral": REFERRAL_REWARD_DAYS,
    }
