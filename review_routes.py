"""
Internal cron routes for scheduled client emails.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from review_email_utils import backfill_registered_at_from_audit_logs, process_review_request_emails

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/internal/cron/review-request-emails")
def cron_review_request_emails(
    db: Session = Depends(get_db),
    cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
):
    expected = os.getenv("CRON_SECRET")
    if not expected or cron_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    backfilled = backfill_registered_at_from_audit_logs(db)
    result = process_review_request_emails(db)
    result["backfilled_registered_at"] = backfilled
    logger.info(
        "Review request cron complete sent=%s failed=%s backfilled=%s",
        result["sent"],
        result["failed"],
        backfilled,
    )
    return {
        "message": "Review request email job complete",
        **result,
    }
