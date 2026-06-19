"""Self-service account deletion routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from account_deletion_utils import delete_user_account
from audit_utils import log_event
from auth_utils import get_current_user, require_role, user_is_platform_admin
from database import get_db
from email_utils import send_account_deleted_admin_email, send_account_deleted_user_email
from models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])


@router.delete("/delete")
def delete_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(user, ["owner"])

    if user_is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Platform admin accounts cannot be deleted from the client dashboard.",
        )

    user_email = user.email
    user_id = user.id

    try:
        log_event(
            user_id=user_id,
            event_type="account_deletion_requested",
            description=f"User requested account deletion for {user_email}",
        )
    except Exception:
        logger.exception("Failed to write pre-deletion audit log user_id=%s", user_id)

    try:
        result = delete_user_account(db, user)
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while deleting account user_id=%s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Unable to delete your account. Please contact support.",
        ) from None
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while deleting account user_id=%s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Unable to delete your account. Please contact support.",
        ) from None

    try:
        send_account_deleted_user_email(to_email=user_email)
    except Exception:
        logger.exception("Failed to send account deleted email to %s", user_email)

    try:
        send_account_deleted_admin_email(
            user_email=result["user_email"],
            business_names=result.get("business_names") or [],
            deleted_at=result.get("deleted_at") or "",
            subscription_canceled=result.get("subscription_canceled", False),
            referral_code=result.get("referral_code"),
            referral_count=result.get("referral_count", 0),
            free_months_earned=result.get("free_months_earned", 0),
        )
    except Exception:
        logger.exception("Failed to send admin account deletion notification")

    logger.info("Account deleted user_id=%s email=%s", user_id, user_email)
    return {
        "message": "Your account has been deleted.",
        "redirect_url": "/billing.html?account_deleted=1",
    }
