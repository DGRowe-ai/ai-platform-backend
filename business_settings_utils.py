from database import SessionLocal
from models import BusinessSettings


def get_settings(business_id: int):
    """
    Fetch settings for a business.
    If none exist yet, create default settings automatically.
    """
    with SessionLocal() as db:
        settings = db.query(BusinessSettings).filter_by(business_id=business_id).first()

        # Auto-create settings if missing
        if not settings:
            settings = BusinessSettings(business_id=business_id)
            db.add(settings)
            db.commit()
            db.refresh(settings)

        return settings


def update_settings(business_id: int, data: dict):
    """
    Update greeting_message, chatbot_tone, and custom_instructions.
    Creates settings if they do not exist.
    """
    with SessionLocal() as db:
        settings = db.query(BusinessSettings).filter_by(business_id=business_id).first()

        # Auto-create if missing
        if not settings:
            settings = BusinessSettings(business_id=business_id)
            db.add(settings)

        # Update fields
        if "greeting_message" in data:
            settings.greeting_message = data["greeting_message"]

        if "chatbot_tone" in data:
            settings.chatbot_tone = data["chatbot_tone"]

        if "custom_instructions" in data:
            settings.custom_instructions = data["custom_instructions"]

        db.commit()
        db.refresh(settings)

        return settings
