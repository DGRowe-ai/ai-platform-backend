import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth_utils import get_current_user, require_platform_admin
from database import get_db
from models import Business, Payment, User
from payment_log_utils import (
    get_payment_log_metadata,
    read_payment_log_entries,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_business(db: Session, business_key: str) -> Business:
    normalized_key = (business_key or "").strip()
    if not normalized_key:
        raise HTTPException(status_code=404, detail="Business not found")

    business = db.query(Business).filter(Business.folder_name == normalized_key).first()
    if not business and normalized_key.isdigit():
        business = db.query(Business).filter(Business.id == int(normalized_key)).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _serialize_db_payment(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "amount": payment.amount,
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
        "next_renewal_date": (
            payment.next_renewal_date.isoformat() if payment.next_renewal_date else None
        ),
        "payment_type": payment.payment_type,
        "note": payment.notes,
        "source": "database",
    }


def _serialize_accounting_business(db: Session, business: Business) -> dict:
    owner = db.query(User).filter(User.id == business.owner_id).first()
    log_metadata = get_payment_log_metadata(business.name)

    return {
        "id": business.id,
        "business_key": business.folder_name,
        "folder_name": business.folder_name,
        "name": business.name,
        "owner_email": owner.email if owner else None,
        "billing_status": (owner.billing_status or "inactive") if owner else "inactive",
        "subscription_active": bool(owner.subscription_active) if owner else False,
        "stripe_customer_id": owner.stripe_customer_id if owner else None,
        "payment_log": log_metadata,
    }


@router.get("/admin/accounting/businesses")
def list_accounting_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)

    businesses = db.query(Business).order_by(Business.name.asc()).all()
    return {
        "businesses": [_serialize_accounting_business(db, business) for business in businesses]
    }


@router.get("/admin/accounting/businesses/{business_key}")
def get_accounting_business_detail(
    business_key: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    business = _resolve_business(db, business_key)
    owner = db.query(User).filter(User.id == business.owner_id).first()

    db_payments = (
        db.query(Payment)
        .filter(Payment.business_id == business.id)
        .order_by(Payment.payment_date.desc())
        .all()
    )

    try:
        file_payments = read_payment_log_entries(business.name)
    except Exception:
        logger.exception(
            "Failed to read payment log for business_key=%s business_name=%s",
            business_key,
            business.name,
        )
        file_payments = []

    log_metadata = get_payment_log_metadata(business.name)

    return {
        "business": {
            "id": business.id,
            "business_key": business.folder_name,
            "folder_name": business.folder_name,
            "name": business.name,
            "owner_email": owner.email if owner else None,
            "billing_status": (owner.billing_status or "inactive") if owner else "inactive",
            "subscription_active": bool(owner.subscription_active) if owner else False,
            "stripe_customer_id": owner.stripe_customer_id if owner else None,
        },
        "payment_log": {
            **log_metadata,
            "entries": file_payments,
        },
        "database_payments": [_serialize_db_payment(payment) for payment in db_payments],
    }
