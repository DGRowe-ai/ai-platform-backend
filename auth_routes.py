"""Authentication routes for password reset."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_utils import hash_password, normalize_email
from database import get_db
from email_utils import send_password_reset_email
from models import User
from password_reset_utils import (
    generate_reset_token,
    hash_reset_token,
    is_reset_token_expired,
    reset_token_expires_at,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_RESET_MESSAGE = "If this email exists, a reset link has been sent."


class RequestPasswordResetBody(BaseModel):
    email: EmailStr


class ValidateResetTokenBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)


class ResetPasswordBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    newPassword: str = Field(..., min_length=8, max_length=256)


def _find_user_by_reset_token(db: Session, raw_token: str) -> User | None:
    token_hash = hash_reset_token(raw_token.strip())
    return (
        db.query(User)
        .filter(User.password_reset_token_hash == token_hash)
        .first()
    )


def _clear_reset_token(user: User) -> None:
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None


@router.post("/request-password-reset")
def request_password_reset(req: RequestPasswordResetBody, db: Session = Depends(get_db)):
    email = normalize_email(str(req.email))

    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            raw_token, token_hash = generate_reset_token()
            user.password_reset_token_hash = token_hash
            user.password_reset_expires_at = reset_token_expires_at()
            db.add(user)
            db.commit()

            try:
                send_password_reset_email(to_email=user.email, reset_token=raw_token)
                logger.info("Password reset email queued for user_id=%s", user.id)
            except Exception:
                logger.exception(
                    "Failed to send password reset email for user_id=%s",
                    user.id,
                )
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error during password reset request for email=%s", email)
    except Exception:
        logger.exception("Unexpected error during password reset request for email=%s", email)

    return {"message": GENERIC_RESET_MESSAGE}


@router.post("/validate-reset-token")
def validate_reset_token(req: ValidateResetTokenBody, db: Session = Depends(get_db)):
    try:
        user = _find_user_by_reset_token(db, req.token)
        valid = bool(
            user
            and user.password_reset_token_hash
            and not is_reset_token_expired(user.password_reset_expires_at)
        )
        return {"valid": valid}
    except SQLAlchemyError:
        logger.exception("Database error while validating reset token")
        return {"valid": False}
    except Exception:
        logger.exception("Unexpected error while validating reset token")
        return {"valid": False}


@router.post("/reset-password")
def reset_password(req: ResetPasswordBody, db: Session = Depends(get_db)):
    if req.newPassword.strip() != req.newPassword:
        raise HTTPException(status_code=400, detail="Password cannot start or end with spaces.")

    try:
        user = _find_user_by_reset_token(db, req.token)
        if not user or not user.password_reset_token_hash:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

        if is_reset_token_expired(user.password_reset_expires_at):
            _clear_reset_token(user)
            db.add(user)
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

        user.password_hash = hash_password(req.newPassword)
        _clear_reset_token(user)
        db.add(user)
        db.commit()

        logger.info("Password reset completed for user_id=%s", user.id)
        return {"message": "Password updated successfully."}
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while resetting password")
        raise HTTPException(status_code=500, detail="Unable to reset password.") from None
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while resetting password")
        raise HTTPException(status_code=500, detail="Unable to reset password.") from None
