"""Self-service account deletion with Stripe cancellation and data cleanup."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth_utils import normalize_email, user_is_platform_admin
from business_utils import BUSINESSES_PATH
from knowledge_utils import get_business_upload_dir
from models import (
    AuditLog,
    BillingCheckoutSession,
    Business,
    BusinessSettings,
    ChatMessage,
    Conversation,
    KnowledgeEmbedding,
    KnowledgeFile,
    MessageLog,
    Payment,
    RateLimit,
    ReferralSignupLog,
    User,
)

logger = logging.getLogger(__name__)


def cancel_user_stripe_subscriptions(user: User) -> list[str]:
    """Cancel all active Stripe subscriptions immediately."""
    canceled_ids: list[str] = []

    if not user.stripe_customer_id or not stripe.api_key:
        return canceled_ids

    try:
        subscriptions = stripe.Subscription.list(
            customer=user.stripe_customer_id,
            status="all",
            limit=20,
        )
    except stripe.error.StripeError:
        logger.exception(
            "Failed to list Stripe subscriptions for user_id=%s",
            user.id,
        )
        return canceled_ids

    for subscription in subscriptions.data:
        if subscription.status not in {"active", "trialing", "past_due", "unpaid"}:
            continue
        try:
            stripe.Subscription.cancel(subscription.id)
            canceled_ids.append(subscription.id)
            logger.info(
                "Canceled Stripe subscription %s for user_id=%s",
                subscription.id,
                user.id,
            )
        except stripe.error.StripeError:
            logger.exception(
                "Failed to cancel Stripe subscription %s for user_id=%s",
                subscription.id,
                user.id,
            )

    return canceled_ids


def _delete_business_data(db: Session, business: Business) -> None:
    business_id = business.id
    folder_name = business.folder_name

    db.query(KnowledgeEmbedding).filter(
        KnowledgeEmbedding.client_id == business_id
    ).delete(synchronize_session=False)

    knowledge_files = (
        db.query(KnowledgeFile).filter(KnowledgeFile.client_id == business_id).all()
    )
    for record in knowledge_files:
        file_path = Path(record.file_path)
        if file_path.exists() and file_path.is_file():
            try:
                file_path.unlink()
            except OSError:
                logger.warning("Could not delete knowledge file path=%s", file_path)
    db.query(KnowledgeFile).filter(KnowledgeFile.client_id == business_id).delete(
        synchronize_session=False
    )

    upload_dir = get_business_upload_dir(business)
    if upload_dir.exists() and folder_name != "template":
        try:
            shutil.rmtree(upload_dir, ignore_errors=True)
        except OSError:
            logger.warning("Could not delete upload dir path=%s", upload_dir)

    db.query(MessageLog).filter(MessageLog.business_id == business_id).delete(
        synchronize_session=False
    )
    db.query(Conversation).filter(Conversation.business_id == business_id).delete(
        synchronize_session=False
    )
    db.query(BusinessSettings).filter(BusinessSettings.business_id == business_id).delete(
        synchronize_session=False
    )
    db.query(ChatMessage).filter(ChatMessage.business_id == business_id).delete(
        synchronize_session=False
    )
    db.query(RateLimit).filter(RateLimit.business_id == business_id).delete(
        synchronize_session=False
    )
    db.query(Payment).filter(Payment.business_id == business_id).delete(
        synchronize_session=False
    )

    db.query(User).filter(
        User.business_id == business_id,
        User.id != business.owner_id,
    ).delete(synchronize_session=False)
    db.delete(business)

    folder_path = BUSINESSES_PATH / folder_name
    if folder_path.exists() and folder_name != "template":
        try:
            shutil.rmtree(folder_path)
        except OSError:
            logger.warning("Could not delete business folder path=%s", folder_path)


def delete_user_account(db: Session, user: User) -> dict:
    """Permanently delete a user account and all associated data."""
    if user_is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Platform admin accounts cannot be deleted from the client dashboard.",
        )

    user_email = user.email
    user_id = user.id
    referral_code = user.referral_code
    referral_count = int(user.referral_count or 0)
    free_months_earned = int(user.free_months_earned or 0)
    referred_by_user_id = user.referred_by_user_id

    businesses = db.query(Business).filter(Business.owner_id == user_id).all()
    business_names = [business.name for business in businesses if business.name]
    business_folders = [business.folder_name for business in businesses]

    canceled_subscription_ids = cancel_user_stripe_subscriptions(user)

    for business in businesses:
        _delete_business_data(db, business)

    db.query(User).filter(User.referred_by_user_id == user_id).update(
        {User.referred_by_user_id: None},
        synchronize_session=False,
    )
    db.query(ReferralSignupLog).filter(
        (ReferralSignupLog.referrer_user_id == user_id)
        | (ReferralSignupLog.referred_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(BillingCheckoutSession).filter(
        BillingCheckoutSession.customer_email == normalize_email(user_email)
    ).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.user_id == user_id).delete(
        synchronize_session=False
    )

    db.delete(user)
    db.commit()

    return {
        "message": "Account deleted",
        "user_email": user_email,
        "user_id": user_id,
        "business_names": business_names,
        "business_folders": business_folders,
        "subscription_canceled": bool(canceled_subscription_ids),
        "canceled_subscription_ids": canceled_subscription_ids,
        "referral_code": referral_code,
        "referral_count": referral_count,
        "free_months_earned": free_months_earned,
        "was_referred": bool(referred_by_user_id),
        "deleted_at": datetime.utcnow().isoformat() + "Z",
    }
