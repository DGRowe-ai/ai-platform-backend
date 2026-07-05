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

VOICE_INSTRUCTION_CHAR_WARN = 14000


def _display_business_name(settings: BusinessSettings, business: Business | None) -> str:
    configured = (getattr(settings, "voice_business_name", None) or "").strip()
    if configured:
        return configured
    if business and business.name:
        return business.name.strip()
    return ""


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
    display_name = _display_business_name(settings, business)
    return {
        "business_id": settings.business_id,
        "businessPhoneNumber": phone,
        "business_phone_number": phone,
        "businessName": display_name,
        "business_name": display_name,
        "voiceBusinessName": display_name,
        "voice_business_name": display_name,
        "tone": settings.voice_tone or "friendly",
        "voice_tone": settings.voice_tone or "friendly",
        "custom_instructions": settings.voice_custom_instructions or "",
        "knowledge": settings.voice_custom_instructions or "",
        "spell_name": bool(getattr(settings, "voice_spell_name", 0)),
        "voice_spell_name": bool(getattr(settings, "voice_spell_name", 0)),
        "greeting_hint": settings.voice_greeting or DEFAULT_VOICE_GREETING,
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

        if "businessName" in data or "voiceBusinessName" in data or "voice_business_name" in data:
            raw_name = (
                data.get("businessName")
                or data.get("voiceBusinessName")
                or data.get("voice_business_name")
            )
            settings.voice_business_name = (raw_name or "").strip()

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
    configured_name = (getattr(settings, "voice_business_name", None) or "").strip()
    name = configured_name or (business_name or "").strip()

    fact_sections: list[str] = []
    if custom:
        fact_sections.append(custom)
    if knowledge_context:
        uploaded = knowledge_context.strip()
        if uploaded and uploaded not in custom:
            fact_sections.append("Uploaded knowledge base files:\n" + uploaded)

    business_facts = "\n\n".join(section for section in fact_sections if section).strip()

    parts = [
        "You are an AI phone receptionist.",
    ]

    if name:
        parts.append(f'You answer calls for the company "{name}".')
        parts.append(
            f'The company name is exactly "{name}". Never shorten it, change it, or substitute a different name.'
        )

    parts.extend([
        "CRITICAL RULES — follow these on every response:",
        "1. Speak only in English unless the caller explicitly asks for another language.",
        "2. Use ONLY the BUSINESS FACTS section below for company details (hours, location, services, pricing, coverage area, etc.).",
        "3. Do not guess, invent, or assume any business detail that is not explicitly stated in BUSINESS FACTS.",
        '4. If asked something not covered in BUSINESS FACTS, say you do not have that information and offer to have someone follow up.',
        "5. When BUSINESS FACTS lists multiple locations or coverage areas, mention all of them — do not omit any.",
        f"6. Use a {tone} tone. Keep answers concise and natural for phone calls.",
    ])

    if business_facts:
        parts.append("BUSINESS FACTS (your only source of truth):\n" + business_facts)
    else:
        parts.append(
            "BUSINESS FACTS: No business facts are configured yet. "
            "Tell callers you are still being set up and offer to have someone call them back."
        )

    if greeting:
        parts.append("Call opening style:\n" + greeting)

    if getattr(settings, "voice_spell_name", 0):
        parts.append(SPELL_NAME_INSTRUCTION)

    instructions = "\n\n".join(part for part in parts if part)

    if len(instructions) > VOICE_INSTRUCTION_CHAR_WARN:
        import logging

        logging.getLogger(__name__).warning(
            "Voice instructions are very long (%s chars) for business_id=%s; "
            "consider shorter bullet points so all facts are followed reliably.",
            len(instructions),
            settings.business_id,
        )

    return instructions
