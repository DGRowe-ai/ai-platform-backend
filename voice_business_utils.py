"""Resolve businesses for inbound voice calls."""

from __future__ import annotations

import os
import re

from sqlalchemy.orm import Session

from models import Business


def normalize_phone_digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def find_business_for_inbound_call(db: Session, to_number: str | None) -> Business | None:
    digits = normalize_phone_digits(to_number)
    if digits:
        businesses = db.query(Business).all()
        for business in businesses:
            business_digits = normalize_phone_digits(business.phone)
            if business_digits and business_digits[-10:] == digits[-10:]:
                return business

    default_key = (os.getenv("DEFAULT_VOICE_BUSINESS_ID") or "").strip()
    if default_key:
        if default_key.isdigit():
            return db.query(Business).filter(Business.id == int(default_key)).first()
        return db.query(Business).filter(Business.folder_name == default_key).first()

    return db.query(Business).order_by(Business.id.asc()).first()
