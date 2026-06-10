from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from auth_utils import get_current_user, require_role
from admin_analytics import get_admin_analytics
from database import SessionLocal
from models import Business, User

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
    require_role(user, ["admin"])
    return get_admin_analytics()

@router.get("/admin/businesses")
def admin_get_all_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(user, ["admin"])

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