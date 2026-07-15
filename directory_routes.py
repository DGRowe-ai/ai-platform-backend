import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth_utils import get_current_user, require_platform_admin
from database import get_db
from models import Business, BusinessSettings, User
from plan_utils import user_tier

logger = logging.getLogger(__name__)

router = APIRouter()


def _serialize_directory_business(db: Session, business: Business) -> dict:
    owner = db.query(User).filter(User.id == business.owner_id).first()
    return {
        "id": business.id,
        "business_key": business.folder_name,
        "folder_name": business.folder_name,
        "name": business.name,
        "email": owner.email if owner else None,
        "owner_email": owner.email if owner else None,
        "phone": business.phone,
    }


def _serialize_client_information(db: Session, business: Business) -> dict:
    owner = db.query(User).filter(User.id == business.owner_id).first()
    settings = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == business.id)
        .first()
    )

    forwarding_enabled = bool(settings and settings.call_forwarding_enabled)
    forwarding_number = (settings.call_forwarding_number or "").strip() if settings else ""
    voice_phone = (settings.voice_business_phone or "").strip() if settings else ""
    business_phone = (business.phone or "").strip() or voice_phone

    return {
        "id": business.id,
        "business_key": business.folder_name,
        "business": business.name,
        "business_name": business.name,
        "name": business.name,
        "owner_email": owner.email if owner else None,
        "email": owner.email if owner else None,
        "tier": user_tier(owner) if owner else None,
        "forwarding_enabled": forwarding_enabled,
        "forwarding_number": forwarding_number or None,
        "business_phone": business_phone or None,
        "phone": business_phone or None,
    }


@router.get("/admin/directory/businesses")
def list_directory_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)

    businesses = db.query(Business).order_by(Business.name.asc()).all()
    return {
        "businesses": [
            _serialize_directory_business(db, business) for business in businesses
        ]
    }


@router.get("/admin/client-information")
def list_client_information(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)

    businesses = db.query(Business).order_by(Business.name.asc()).all()
    clients = [_serialize_client_information(db, business) for business in businesses]
    return {
        "clients": clients,
        "count": len(clients),
    }
