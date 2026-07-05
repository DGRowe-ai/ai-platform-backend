"""Resolve businesses for inbound voice calls."""

from __future__ import annotations

import logging
import os
import re

from sqlalchemy.orm import Session

from models import Business, BusinessSettings

logger = logging.getLogger(__name__)


def normalize_phone_digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _match_business_by_phone_tail(db: Session, phone_tail: str) -> Business | None:
    if len(phone_tail) < 10:
        return None

    tail = phone_tail[-10:]

    settings_rows = db.query(BusinessSettings).all()
    for settings in settings_rows:
        stored_digits = normalize_phone_digits(getattr(settings, "voice_business_phone", None) or "")
        if stored_digits and stored_digits[-10:] == tail:
            business = db.query(Business).filter(Business.id == settings.business_id).first()
            if business:
                return business

    for business in db.query(Business).all():
        business_digits = normalize_phone_digits(business.phone)
        if business_digits and business_digits[-10:] == tail:
            return business

    return None


def find_business_for_inbound_call(
    db: Session,
    *,
    to_number: str | None = None,
    from_number: str | None = None,
    forwarded_from: str | None = None,
) -> Business | None:
    """Identify the business for a forwarded Twilio call."""
    lookup_numbers = [forwarded_from, from_number]
    for raw_number in lookup_numbers:
        if not raw_number:
            continue
        digits = normalize_phone_digits(raw_number)
        business = _match_business_by_phone_tail(db, digits)
        if business:
            logger.info(
                "Matched inbound call to business_id=%s using number=%s",
                business.id,
                raw_number,
            )
            return business

    if forwarded_from:
        logger.warning(
            "No business matched ForwardedFrom=%s; voice settings will not load",
            forwarded_from,
        )
    elif from_number:
        logger.warning(
            "Inbound call From=%s with no ForwardedFrom. "
            "Save your business phone in the Voicebot dashboard and forward that number to Twilio.",
            from_number,
        )

    default_key = (os.getenv("DEFAULT_VOICE_BUSINESS_ID") or "").strip()
    if default_key:
        if default_key.isdigit():
            business = db.query(Business).filter(Business.id == int(default_key)).first()
            if business:
                logger.info("Using DEFAULT_VOICE_BUSINESS_ID business_id=%s", business.id)
                return business
        business = db.query(Business).filter(Business.folder_name == default_key).first()
        if business:
            logger.info("Using DEFAULT_VOICE_BUSINESS_ID folder=%s", business.folder_name)
            return business

    return None
