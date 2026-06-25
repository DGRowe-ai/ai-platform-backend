"""
Send and schedule the one-week post-subscription Google review request email.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from email_utils import send_review_request_email
from models import AuditLog, Business, User

logger = logging.getLogger(__name__)

REVIEW_EMAIL_DELAY_DAYS = 7
GOOGLE_REVIEW_URL = "https://share.google/HIvgRJCoeZ1NLXap0"


def _parse_audit_timestamp(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def get_user_registration_time(db: Session, user: User) -> datetime | None:
    if user.registered_at:
        return user.registered_at

    signup_log = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user.id,
            AuditLog.event_type == "signup",
        )
        .order_by(AuditLog.timestamp.asc())
        .first()
    )
    if signup_log:
        return _parse_audit_timestamp(signup_log.timestamp)

    return None


def user_is_eligible_for_review_email(db: Session, user: User, *, now: datetime | None = None) -> bool:
    if user.review_request_email_sent_at:
        return False

    if not user.email:
        return False

    if user.role not in ("owner", "admin"):
        return False

    billing_status = (user.billing_status or "").strip().lower()
    if not user.subscription_active and billing_status != "active":
        return False

    if not user.business_id:
        business = db.query(Business).filter(Business.owner_id == user.id).first()
        if not business:
            return False

    registered_at = get_user_registration_time(db, user)
    if not registered_at:
        return False

    current_time = now or datetime.utcnow()
    return registered_at <= current_time - timedelta(days=REVIEW_EMAIL_DELAY_DAYS)


def find_users_due_for_review_email(db: Session, *, now: datetime | None = None) -> list[User]:
    current_time = now or datetime.utcnow()
    candidates = (
        db.query(User)
        .filter(User.review_request_email_sent_at.is_(None))
        .all()
    )
    return [
        user
        for user in candidates
        if user_is_eligible_for_review_email(db, user, now=current_time)
    ]


def get_business_name_for_user(db: Session, user: User) -> str:
    business = None
    if user.business_id:
        business = db.query(Business).filter(Business.id == user.business_id).first()
    if not business:
        business = db.query(Business).filter(Business.owner_id == user.id).first()
    return business.name if business and business.name else "your business"


def process_review_request_emails(db: Session, *, now: datetime | None = None) -> dict:
    due_users = find_users_due_for_review_email(db, now=now)
    sent = 0
    failed = 0
    errors: list[str] = []

    for user in due_users:
        business_name = get_business_name_for_user(db, user)
        try:
            send_review_request_email(
                to_email=user.email,
                business_name=business_name,
            )
            user.review_request_email_sent_at = now or datetime.utcnow()
            db.add(user)
            db.commit()
            sent += 1
            logger.info("Sent review request email to user_id=%s", user.id)
        except Exception as exc:
            db.rollback()
            failed += 1
            message = f"user_id={user.id}: {exc}"
            errors.append(message)
            logger.exception("Failed to send review request email to user_id=%s", user.id)

    return {
        "checked": len(due_users),
        "sent": sent,
        "failed": failed,
        "errors": errors,
    }


def backfill_registered_at_from_audit_logs(db: Session) -> int:
    updated = 0
    users = db.query(User).filter(User.registered_at.is_(None)).all()
    for user in users:
        registered_at = get_user_registration_time(db, user)
        if registered_at:
            user.registered_at = registered_at
            db.add(user)
            updated += 1
    if updated:
        db.commit()
    return updated
