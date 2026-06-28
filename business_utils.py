import logging
import shutil
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import (
    Business,
    BusinessSettings,
    ChatMessage,
    Conversation,
    MessageLog,
    RateLimit,
    User,
)

logger = logging.getLogger(__name__)

BUSINESSES_PATH = Path(__file__).resolve().parent / "businesses"
TEMPLATE_PATH = BUSINESSES_PATH / "template"


def create_business_for_user(
    db: Session,
    user,
    business_name: str,
    business_phone: str | None = None,
):
    """Create a new business folder for a user by copying the template."""
    try:
        if not user or not business_name:
            raise ValueError("User and business_name are required")

        folder_name = business_name.lower().replace(" ", "_").replace("-", "_")
        new_path = BUSINESSES_PATH / folder_name

        if new_path.exists():
            raise Exception(f"Business folder already exists: {folder_name}")

        if not TEMPLATE_PATH.exists():
            raise Exception(f"Template folder not found: {TEMPLATE_PATH}")

        logger.info("Creating business folder: %s", folder_name)
        shutil.copytree(TEMPLATE_PATH, new_path)

        business = Business(
            name=business_name,
            folder_name=folder_name,
            owner_id=user.id,
            phone=business_phone,
        )

        db.add(business)
        db.commit()
        db.refresh(business)

        from appointment_utils import ensure_business_knowledge_file

        ensure_business_knowledge_file(business.folder_name)

        logger.info("Business created successfully: %s (ID: %s)", folder_name, business.id)
        return business

    except Exception as e:
        logger.error(
            "Error creating business for user %s: %s",
            getattr(user, "id", None),
            str(e),
        )
        db.rollback()
        raise


def get_business_by_key(db: Session, business_key: str) -> Business | None:
    """Look up a business by numeric id or folder name."""
    normalized_key = (business_key or "").strip()
    if not normalized_key:
        return None

    filters = [Business.folder_name == normalized_key]
    if normalized_key.isdigit():
        filters.append(Business.id == int(normalized_key))

    return db.query(Business).filter(or_(*filters)).first()


def delete_business_for_admin(db: Session, business_key: str) -> dict:
    """Delete a client business, related records, and its on-disk folder."""
    from auth_utils import user_is_platform_admin

    business = get_business_by_key(db, business_key)
    if not business:
        raise ValueError("Business not found")

    if business.folder_name == "template":
        raise ValueError("Cannot delete the template business")

    owner_id = business.owner_id
    business_id = business.id
    folder_name = business.folder_name

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
    db.query(User).filter(User.business_id == business_id).delete(synchronize_session=False)

    db.delete(business)
    db.flush()

    if owner_id:
        owner = db.query(User).filter(User.id == owner_id).first()
        if owner:
            remaining_businesses = (
                db.query(Business).filter(Business.owner_id == owner_id).count()
            )
            if remaining_businesses == 0 and not user_is_platform_admin(owner):
                db.delete(owner)

    db.commit()

    folder_path = BUSINESSES_PATH / folder_name
    if folder_path.exists() and folder_name != "template":
        shutil.rmtree(folder_path)

    logger.info("Deleted business %s (%s)", folder_name, business_id)
    return {
        "message": "Business deleted",
        "business_id": folder_name,
        "folder_name": folder_name,
    }
