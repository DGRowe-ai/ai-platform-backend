"""Voicebot settings stored on business_settings."""

from __future__ import annotations

from database import SessionLocal
from models import Business, BusinessSettings
from appointment_utils import seed_appointment_knowledge
from phone_utils import InvalidBusinessPhoneError, normalize_business_phone

DEFAULT_VOICE_GREETING = (
    "When the call begins, greet the caller warmly and ask how you can help."
)

SPELL_NAME_INSTRUCTION = (
    "When a caller provides their name, politely ask them to spell it out "
    "so you can confirm you have it correct."
)


def _get_or_create_settings(db, business_id: int) -> BusinessSettings:
    settings = db.query(BusinessSettings).filter_by(business_id=business_id).first()
    if not settings:
        settings = BusinessSettings(business_id=business_id)
        seed_appointment_knowledge(settings)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def serialize_voice_settings(settings: BusinessSettings, business: Business | None = None) -> dict:
    phone = getattr(settings, "voice_business_phone", None) or ""
    return {
        "business_id": settings.business_id,
        "businessPhoneNumber": phone,
        "business_phone_number": phone,
        "tone": settings.voice_tone or "friendly",
        "voice_tone": settings.voice_tone or "friendly",
        "custom_instructions": settings.voice_custom_instructions or "",
        "knowledge": settings.voice_custom_instructions or "",
        "spell_name": bool(getattr(settings, "voice_spell_name", 0)),
        "voice_spell_name": bool(getattr(settings, "voice_spell_name", 0)),
        "greeting_hint": settings.voice_greeting or DEFAULT_VOICE_GREETING,
        "businessName": business.name if business else "",
        "business_name": business.name if business else "",
    }


def get_voice_settings(business_id: int) -> dict:
    with SessionLocal() as db:
        settings = _get_or_create_settings(db, business_id)
        business = db.query(Business).filter(Business.id == business_id).first()
        return serialize_voice_settings(settings, business)


def update_voice_settings(business_id: int, data: dict) -> dict:
    with SessionLocal() as db:
        settings = _get_or_create_settings(db, business_id)
        business = db.query(Business).filter(Business.id == business_id).first()

        if "businessPhoneNumber" in data or "business_phone_number" in data:
            raw_phone = data.get("businessPhoneNumber", data.get("business_phone_number"))
            if raw_phone is None or not str(raw_phone).strip():
                settings.voice_business_phone = ""
            else:
                try:
                    settings.voice_business_phone = normalize_business_phone(str(raw_phone))
                except InvalidBusinessPhoneError as exc:
                    raise ValueError(str(exc)) from exc

        if "tone" in data or "voice_tone" in data:
            settings.voice_tone = (data.get("tone") or data.get("voice_tone") or "friendly").strip()

        if "custom_instructions" in data or "knowledge" in data:
            value = data.get("custom_instructions")
            if value is None:
                value = data.get("knowledge")
            settings.voice_custom_instructions = (value or "").strip()

        if "spell_name" in data or "voice_spell_name" in data:
            raw = data.get("spell_name", data.get("voice_spell_name"))
            settings.voice_spell_name = 1 if raw else 0

        if "greeting_hint" in data or "voice_greeting" in data:
            value = data.get("greeting_hint", data.get("voice_greeting"))
            settings.voice_greeting = (value or DEFAULT_VOICE_GREETING).strip()

        db.commit()
        db.refresh(settings)
        return serialize_voice_settings(settings, business)


def build_voice_realtime_instructions(
    settings: BusinessSettings,
    knowledge_context: str = "",
    business_name: str = "",
) -> str:
    tone = (settings.voice_tone or "friendly").strip()
    custom = (settings.voice_custom_instructions or "").strip()
    greeting = (settings.voice_greeting or DEFAULT_VOICE_GREETING).strip()
    name = (business_name or "").strip()

    parts = [
        "You are a friendly, natural-sounding AI phone receptionist.",
    ]

    if name:
        parts.append(f"You are answering calls for {name}.")

    parts.extend([
        f"Use a {tone} tone in every response.",
        greeting,
        "Keep answers concise and conversational for phone calls.",
    ])

    if custom:
        parts.append("Business knowledge and instructions:\n" + custom)

    if knowledge_context:
        parts.append("Relevant knowledge base excerpts:\n" + knowledge_context)

    if getattr(settings, "voice_spell_name", 0):
        parts.append(SPELL_NAME_INSTRUCTION)

    return "\n\n".join(part for part in parts if part)
