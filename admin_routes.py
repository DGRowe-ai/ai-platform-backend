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
