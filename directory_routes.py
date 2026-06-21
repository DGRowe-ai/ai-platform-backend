import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth_utils import get_current_user, require_platform_admin
from database import get_db
from models import Business, User

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
