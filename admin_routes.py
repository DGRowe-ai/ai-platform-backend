from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from auth_utils import get_current_user, require_platform_admin
from admin_analytics import get_admin_analytics
from business_utils import delete_business_for_admin
from database import SessionLocal
from models import Business, User
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================
# ADMIN‑ONLY ANALYTICS ENDPOINT
# ============================
@router.get("/admin/analytics")
def admin_analytics(user=Depends(get_current_user)):
    require_platform_admin(user)
    return get_admin_analytics()

@router.get("/admin/businesses")
def admin_get_all_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)

    output = []
    rows = (
        db.query(Business, User.email, User.subscription_active)
        .outerjoin(User, Business.owner_id == User.id)
        .all()
    )

    for business, owner_email, subscription_active in rows:
        output.append({
            "id": business.id,
            "business_id": business.folder_name,
            "business_name": business.name,
            "owner_id": business.owner_id,
            "owner_email": owner_email,
            "subscription_active": bool(subscription_active),
        })

    return output


@router.delete("/admin/businesses/{business_key}")
def admin_delete_business(
    business_key: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)

    try:
        result = delete_business_for_admin(db, business_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while deleting business_key=%s", business_key)
        raise HTTPException(status_code=500, detail="Unable to delete business")
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while deleting business_key=%s", business_key)
        raise HTTPException(status_code=500, detail="Unable to delete business")

    return result