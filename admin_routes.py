from fastapi import APIRouter, Depends
from auth_utils import get_current_user, require_role
from admin_analytics import get_admin_analytics

router = APIRouter()

# ============================
# ADMIN‑ONLY ANALYTICS ENDPOINT
# ============================
@router.get("/admin/analytics")
def admin_analytics(user=Depends(get_current_user)):
    require_role(user, ["admin"])
    return get_admin_analytics()

from models import Business  # make sure this import exists

@router.get("/admin/businesses")
def admin_get_all_businesses(user=Depends(get_current_user)):
    require_role(user, ["admin"])

    businesses = Business.query.all()

    output = []
    for b in businesses:
        output.append({
            "business_id": b.folder_name,
            "business_name": b.name,
            "owner_email": b.owner_email,
            "subscription_active": b.subscription_active,
            "created_at": b.created_at,
            "last_payment": b.last_payment
        })

    return output
