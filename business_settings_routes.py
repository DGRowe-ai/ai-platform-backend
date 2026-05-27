from fastapi import APIRouter, Depends, HTTPException
from backend.auth_utils import get_current_user, require_role
from backend.business_settings_utils import get_settings, update_settings

router = APIRouter()

# ============================
# GET BUSINESS SETTINGS (Owner Only)
# ============================
@router.get("/business/settings")
def fetch_settings(user=Depends(get_current_user)):
    require_role(user, ["owner"])
    return get_settings(user.business_id)


# ============================
# UPDATE BUSINESS SETTINGS (Owner Only)
# ============================
@router.post("/business/settings")
def save_settings(data: dict, user=Depends(get_current_user)):
    require_role(user, ["owner"])
    return update_settings(user.business_id, data)
