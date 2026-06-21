"""
Widget customization API routes.

Authenticated clients can read and update their own widget settings.
Public embed scripts fetch sanitized settings by business folder name.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlalchemy.orm import Session

from auth_utils import ALGORITHM, SECRET_KEY, require_role
from business_utils import get_business_by_key
from database import get_db
from models import Business, User
from widget_settings_utils import (
    get_widget_settings_for_business,
    save_widget_settings_for_business,
    serialize_public_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/widget", tags=["widget"])
optional_bearer = HTTPBearer(auto_error=False)

UPLOADS_ROOT = Path(__file__).resolve().parent / "uploads" / "widget_avatars"
ALLOWED_AVATAR_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _get_api_public_base_url() -> str:
    return (
        os.getenv("API_PUBLIC_URL")
        or os.getenv("BACKEND_PUBLIC_URL")
        or "https://ai-platform-backend-ulqs.onrender.com"
    ).rstrip("/")


def _cors_public_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }


def _resolve_client_business(db: Session, client_id: str) -> Business:
    business = get_business_by_key(db, client_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _get_client_business(db: Session, user: User) -> Business:
    business = None

    if user.business_id:
        business = db.query(Business).filter(Business.id == user.business_id).first()

    if not business and user.role == "owner":
        business = db.query(Business).filter(Business.owner_id == user.id).first()

    if not business:
        business = db.query(Business).filter(Business.owner_id == user.id).first()

    if not business:
        raise HTTPException(
            status_code=404,
            detail="No business is linked to this account.",
        )

    if user.role == "owner" and business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return business


def _get_user_from_token(db: Session, token: str) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _get_authenticated_business(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
) -> Business:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = _get_user_from_token(db, credentials.credentials)
    require_role(user, ["owner", "admin", "staff"])
    return _get_client_business(db, user)


@router.options("/settings/public")
@router.options("/avatar/{client_id}")
async def widget_public_options():
    return Response(status_code=204, headers=_cors_public_headers())


@router.get("/settings/public")
def get_public_widget_settings(
    client_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    business = _resolve_client_business(db, client_id)
    settings = get_widget_settings_for_business(db, business.id)
    body = {
        "client_id": business.folder_name,
        "settings": serialize_public_settings(settings),
    }
    return JSONResponse(content=body, headers=_cors_public_headers())


@router.get("/settings")
def get_widget_settings(
    client_id: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(get_db),
):
    # Public embed path used by widget.js on customer websites.
    if client_id:
        return get_public_widget_settings(client_id=client_id, db=db)

    business = _get_authenticated_business(db, credentials)
    settings = get_widget_settings_for_business(db, business.id)
    return {
        "business_id": business.id,
        "client_id": business.folder_name,
        "settings": settings,
    }


@router.post("/settings")
def save_widget_settings(
    payload: dict,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(get_db),
):
    business = _get_authenticated_business(db, credentials)
    try:
        settings = save_widget_settings_for_business(db, business.id, payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc

    return {
        "message": "Widget settings saved",
        "business_id": business.id,
        "client_id": business.folder_name,
        "settings": settings,
    }


@router.post("/avatar")
async def upload_widget_avatar(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(get_db),
):
    business = _get_authenticated_business(db, credentials)
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Avatar must be a PNG, JPG, WEBP, or GIF image",
        )

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded avatar file is empty")
    if len(raw_bytes) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar must be 2MB or smaller")

    business_dir = UPLOADS_ROOT / business.folder_name
    business_dir.mkdir(parents=True, exist_ok=True)

    for existing in business_dir.glob("avatar.*"):
        existing.unlink(missing_ok=True)

    extension = ALLOWED_AVATAR_TYPES[content_type]
    avatar_path = business_dir / f"avatar{extension}"
    avatar_path.write_bytes(raw_bytes)

    avatar_url = f"{_get_api_public_base_url()}/api/widget/avatar/{business.folder_name}"
    current_settings = get_widget_settings_for_business(db, business.id)
    current_settings["avatarUrl"] = avatar_url
    current_settings["showAvatar"] = True
    settings = save_widget_settings_for_business(db, business.id, current_settings)

    return {
        "message": "Avatar uploaded",
        "avatarUrl": avatar_url,
        "settings": settings,
    }


@router.get("/avatar/{client_id}")
def get_widget_avatar(client_id: str, db: Session = Depends(get_db)):
    business = _resolve_client_business(db, client_id)
    business_dir = UPLOADS_ROOT / business.folder_name
    if not business_dir.exists():
        raise HTTPException(status_code=404, detail="Avatar not found")

    matches = sorted(business_dir.glob("avatar.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Avatar not found")

    avatar_path = matches[0]
    return FileResponse(
        avatar_path,
        media_type=_media_type_for_suffix(avatar_path.suffix),
        headers=_cors_public_headers(),
    )


def _media_type_for_suffix(suffix: str) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")
