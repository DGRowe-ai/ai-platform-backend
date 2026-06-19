"""Secure password reset token helpers."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta

from auth_utils import SECRET_KEY

RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "30"))


def generate_reset_token() -> tuple[str, str]:
    """Return (raw_token, hashed_token) for storage."""
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_reset_token(raw_token)


def hash_reset_token(raw_token: str) -> str:
    pepper = SECRET_KEY or "password-reset-pepper"
    return hashlib.sha256(f"{pepper}:{raw_token}".encode("utf-8")).hexdigest()


def reset_token_expires_at() -> datetime:
    return datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)


def is_reset_token_expired(expires_at: datetime | None) -> bool:
    if not expires_at:
        return True
    return expires_at <= datetime.utcnow()
