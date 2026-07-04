"""Send voicebot and duo welcome emails without duplicating chatbot welcome logic."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from email_utils import send_duo_welcome_email, send_voicebot_welcome_email
from models import Business, User
from plan_utils import PLAN_CHATBOT, PLAN_DUO, PLAN_VOICEBOT, user_plan_type

logger = logging.getLogger(__name__)


def _client_name_for_user(db: Session, user: User, fallback: str = "") -> str:
    if fallback.strip():
        return fallback.strip()
    if user.business_id:
        business = db.query(Business).filter(Business.id == user.business_id).first()
        if business and business.name:
            return business.name
    owned = db.query(Business).filter(Business.owner_id == user.id).first()
    if owned and owned.name:
        return owned.name
    return user.email.split("@")[0]


def send_product_welcome_emails_if_needed(
    db: Session,
    user: User,
    *,
    client_name: str = "",
) -> None:
    """Send voicebot or duo welcome emails once per user."""
    plan = user_plan_type(user)
    name = _client_name_for_user(db, user, client_name)

    if plan == PLAN_DUO:
        if user.duo_welcome_email_sent_at:
            return
        send_duo_welcome_email(to_email=user.email, client_name=name)
        user.duo_welcome_email_sent_at = datetime.utcnow()
        db.add(user)
        db.commit()
        logger.info("Sent duo welcome email to user_id=%s", user.id)
        return

    if plan == PLAN_VOICEBOT:
        if user.voicebot_welcome_email_sent_at:
            return
        send_voicebot_welcome_email(to_email=user.email, client_name=name)
        user.voicebot_welcome_email_sent_at = datetime.utcnow()
        db.add(user)
        db.commit()
        logger.info("Sent voicebot welcome email to user_id=%s", user.id)


def should_send_chatbot_welcome_email(user: User) -> bool:
    return user_plan_type(user) == PLAN_CHATBOT
