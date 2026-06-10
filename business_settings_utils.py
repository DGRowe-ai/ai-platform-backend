from database import SessionLocal
from models import BusinessSettings
import json


def _parse_faq_items(raw_faq_items):
    if not raw_faq_items:
        return []

    try:
        parsed = json.loads(raw_faq_items)
    except (TypeError, json.JSONDecodeError):
        return []

    return parsed if isinstance(parsed, list) else []


def serialize_settings(settings: BusinessSettings):
    return {
        "business_id": settings.business_id,
        "welcome_message": settings.greeting_message,
        "greeting_message": settings.greeting_message,
        "tone": settings.chatbot_tone,
        "chatbot_tone": settings.chatbot_tone,
        "chat_length": settings.max_response_length,
        "max_response_length": settings.max_response_length,
        "custom_instructions": settings.custom_instructions or "",
        "faqs": _parse_faq_items(settings.faq_items),
    }


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

        return serialize_settings(settings)


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

        if "welcome_message" in data:
            settings.greeting_message = data["welcome_message"]

        if "chatbot_tone" in data:
            settings.chatbot_tone = data["chatbot_tone"]

        if "tone" in data:
            settings.chatbot_tone = data["tone"]

        if "max_response_length" in data:
            settings.max_response_length = int(data["max_response_length"])

        if "chat_length" in data:
            settings.max_response_length = int(data["chat_length"])

        if "custom_instructions" in data:
            settings.custom_instructions = data["custom_instructions"]

        if "faqs" in data:
            settings.faq_items = json.dumps(data["faqs"])

        db.commit()
        db.refresh(settings)

        return serialize_settings(settings)
