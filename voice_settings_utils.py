"""Voicebot settings stored on business_settings."""

from __future__ import annotations

import json
import logging

from database import SessionLocal
from models import Business, BusinessSettings, User
from appointment_utils import seed_appointment_knowledge
from phone_utils import InvalidBusinessPhoneError, normalize_business_phone
from plan_utils import (
    get_voice_capability_tier,
    tier_allows_call_forwarding,
    tier_allows_custom_personality,
    tier_allows_follow_ups,
    tier_allows_multi_location,
    tier_is_premium,
    user_tier,
)

logger = logging.getLogger(__name__)

DEFAULT_VOICE_GREETING = (
    "When the call begins, greet the caller warmly and ask how you can help."
)

SPELL_NAME_INSTRUCTION = (
    "When a caller provides their name, politely ask them to spell it out "
    "so you can confirm you have it correct."
)

VOICE_INSTRUCTION_CHAR_WARN = 14000
DEFAULT_PERSONALITY = "friendly"


def _display_business_name(settings: BusinessSettings, business: Business | None) -> str:
    configured = (getattr(settings, "voice_business_name", None) or "").strip()
    if configured:
        return configured
    if business and business.name:
        return business.name.strip()
    return ""


def _parse_locations(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    locations = []
    for item in data:
        if not isinstance(item, dict):
            continue
        locations.append(
            {
                "name": str(item.get("name") or "").strip(),
                "address": str(item.get("address") or "").strip(),
                "phone": str(item.get("phone") or "").strip(),
                "hours": str(item.get("hours") or "").strip(),
                "services": str(item.get("services") or "").strip(),
                "staff": str(item.get("staff") or "").strip(),
                "knowledge": str(item.get("knowledge") or "").strip(),
                "personality": str(item.get("personality") or "").strip(),
                "forwarding_number": str(item.get("forwarding_number") or "").strip(),
            }
        )
    return locations


def _serialize_locations(locations: list) -> str:
    cleaned = []
    for item in locations or []:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "name": str(item.get("name") or "").strip(),
                "address": str(item.get("address") or "").strip(),
                "phone": str(item.get("phone") or "").strip(),
                "hours": str(item.get("hours") or "").strip(),
                "services": str(item.get("services") or "").strip(),
                "staff": str(item.get("staff") or "").strip(),
                "knowledge": str(item.get("knowledge") or "").strip(),
                "personality": str(item.get("personality") or "").strip(),
                "forwarding_number": str(item.get("forwarding_number") or "").strip(),
            }
        )
    return json.dumps(cleaned)


def _get_or_create_settings(db, business_id: int) -> BusinessSettings:
    settings = db.query(BusinessSettings).filter_by(business_id=business_id).first()
    if not settings:
        settings = BusinessSettings(business_id=business_id)
        seed_appointment_knowledge(settings)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _owner_tier_for_business(db, business: Business | None) -> str | None:
    if not business or not business.owner_id:
        return None
    owner = db.query(User).filter(User.id == business.owner_id).first()
    if not owner:
        return None
    return user_tier(owner)


def serialize_voice_settings(
    settings: BusinessSettings,
    business: Business | None = None,
    *,
    tier: str | None = None,
) -> dict:
    phone = getattr(settings, "voice_business_phone", None) or ""
    display_name = _display_business_name(settings, business)
    locations = _parse_locations(getattr(settings, "locations_json", None))
    multi_enabled = bool(getattr(settings, "multi_location_enabled", 0))
    voice_level = get_voice_capability_tier(tier) if tier else None
    can_multi = tier_allows_multi_location(tier) if tier else False
    if not can_multi:
        multi_enabled = False

    tone = settings.voice_tone or DEFAULT_PERSONALITY
    if tier and not tier_allows_custom_personality(tier):
        tone = DEFAULT_PERSONALITY

    return {
        "business_id": settings.business_id,
        "businessPhoneNumber": phone,
        "business_phone_number": phone,
        "businessName": display_name,
        "business_name": display_name,
        "voiceBusinessName": display_name,
        "voice_business_name": display_name,
        "tone": tone,
        "voice_tone": tone,
        "custom_instructions": settings.voice_custom_instructions or "",
        "knowledge": settings.voice_custom_instructions or "",
        "spell_name": bool(getattr(settings, "voice_spell_name", 0)),
        "voice_spell_name": bool(getattr(settings, "voice_spell_name", 0)),
        "greeting_hint": settings.voice_greeting or DEFAULT_VOICE_GREETING,
        "couponUsed": getattr(settings, "voice_coupon_used", None) or "",
        "coupon_used": getattr(settings, "voice_coupon_used", None) or "",
        "multiLocationEnabled": multi_enabled and can_multi,
        "multi_location_enabled": multi_enabled and can_multi,
        "locations": locations if (multi_enabled and can_multi) else [],
        "callForwardingEnabled": bool(getattr(settings, "call_forwarding_enabled", 0))
        and tier_allows_call_forwarding(tier),
        "call_forwarding_enabled": bool(getattr(settings, "call_forwarding_enabled", 0))
        and tier_allows_call_forwarding(tier),
        "callForwardingNumber": getattr(settings, "call_forwarding_number", None) or "",
        "call_forwarding_number": getattr(settings, "call_forwarding_number", None) or "",
        "monthlyOptimization": bool(getattr(settings, "monthly_optimization", 0)) and tier_is_premium(tier),
        "dedicatedSupport": bool(getattr(settings, "dedicated_support", 0)) and tier_is_premium(tier),
        "tier": tier,
        "voice_tier": voice_level,
        "features": {
            "multi_location": can_multi,
            "call_forwarding": tier_allows_call_forwarding(tier) if tier else False,
            "custom_personality": tier_allows_custom_personality(tier) if tier else False,
            "follow_up_questions": tier_allows_follow_ups(tier) if tier else False,
            "custom_workflows": tier_is_premium(tier) if tier else False,
            "monthly_optimization": tier_is_premium(tier) if tier else False,
            "dedicated_support": tier_is_premium(tier) if tier else False,
        },
    }


def get_voice_settings(business_id: int) -> dict:
    with SessionLocal() as db:
        settings = _get_or_create_settings(db, business_id)
        business = db.query(Business).filter(Business.id == business_id).first()
        tier = _owner_tier_for_business(db, business)
        return serialize_voice_settings(settings, business, tier=tier)


def update_voice_settings(business_id: int, data: dict) -> dict:
    with SessionLocal() as db:
        settings = _get_or_create_settings(db, business_id)
        business = db.query(Business).filter(Business.id == business_id).first()
        tier = _owner_tier_for_business(db, business)

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
            if tier_allows_custom_personality(tier):
                settings.voice_tone = (data.get("tone") or data.get("voice_tone") or DEFAULT_PERSONALITY).strip()
            else:
                settings.voice_tone = DEFAULT_PERSONALITY

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

        if tier_allows_multi_location(tier):
            if "multiLocationEnabled" in data or "multi_location_enabled" in data:
                raw = data.get("multiLocationEnabled", data.get("multi_location_enabled"))
                settings.multi_location_enabled = 1 if raw else 0
            if "locations" in data:
                settings.locations_json = _serialize_locations(data.get("locations") or [])
        else:
            settings.multi_location_enabled = 0

        if tier_allows_call_forwarding(tier):
            if "callForwardingEnabled" in data or "call_forwarding_enabled" in data:
                raw = data.get("callForwardingEnabled", data.get("call_forwarding_enabled"))
                settings.call_forwarding_enabled = 1 if raw else 0
            if "callForwardingNumber" in data or "call_forwarding_number" in data:
                settings.call_forwarding_number = (
                    data.get("callForwardingNumber")
                    or data.get("call_forwarding_number")
                    or ""
                ).strip()
        else:
            settings.call_forwarding_enabled = 0

        if tier_is_premium(tier):
            if "monthlyOptimization" in data or "monthly_optimization" in data:
                raw = data.get("monthlyOptimization", data.get("monthly_optimization"))
                settings.monthly_optimization = 1 if raw else 0
            if "dedicatedSupport" in data or "dedicated_support" in data:
                raw = data.get("dedicatedSupport", data.get("dedicated_support"))
                settings.dedicated_support = 1 if raw else 0
            if "customWorkflows" in data or "custom_workflows" in data:
                workflows = data.get("customWorkflows", data.get("custom_workflows")) or []
                settings.custom_workflows_json = json.dumps(workflows)

        db.commit()
        db.refresh(settings)
        return serialize_voice_settings(settings, business, tier=tier)


def record_voicebot_coupon_used(business_id: int, coupon_code: str) -> None:
    normalized = (coupon_code or "").strip().upper()
    if not normalized:
        return

    with SessionLocal() as db:
        settings = _get_or_create_settings(db, business_id)
        settings.voice_coupon_used = normalized
        db.commit()


def _location_facts_block(locations: list[dict]) -> str:
    blocks = []
    for index, loc in enumerate(locations, start=1):
        name = loc.get("name") or f"Location {index}"
        parts = [f"Location {index}: {name}"]
        for key, label in (
            ("address", "Address"),
            ("phone", "Phone"),
            ("hours", "Hours"),
            ("services", "Services"),
            ("staff", "Staff"),
            ("knowledge", "Knowledge"),
            ("personality", "Personality"),
            ("forwarding_number", "Forwarding number"),
        ):
            value = (loc.get(key) or "").strip()
            if value:
                parts.append(f"{label}: {value}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def build_voice_realtime_instructions(
    settings: BusinessSettings,
    knowledge_context: str = "",
    business_name: str = "",
    *,
    tier: str | None = None,
) -> str:
    voice_level = get_voice_capability_tier(tier)
    allow_custom = tier_allows_custom_personality(tier) if tier else True
    allow_follow_ups = tier_allows_follow_ups(tier) if tier else True
    allow_forwarding = tier_allows_call_forwarding(tier) if tier else False
    allow_multi = tier_allows_multi_location(tier) if tier else False
    is_premium = tier_is_premium(tier) if tier else False

    tone = (settings.voice_tone or DEFAULT_PERSONALITY).strip()
    if not allow_custom:
        tone = DEFAULT_PERSONALITY

    custom = (settings.voice_custom_instructions or "").strip()
    greeting = (settings.voice_greeting or DEFAULT_VOICE_GREETING).strip()
    configured_name = (getattr(settings, "voice_business_name", None) or "").strip()
    name = configured_name or (business_name or "").strip()
    locations = _parse_locations(getattr(settings, "locations_json", None))
    multi_enabled = bool(getattr(settings, "multi_location_enabled", 0)) and allow_multi and locations

    fact_sections: list[str] = []
    if custom:
        fact_sections.append(custom)
    if knowledge_context:
        uploaded = knowledge_context.strip()
        if uploaded and uploaded not in custom:
            fact_sections.append("Uploaded knowledge base files:\n" + uploaded)
    if multi_enabled:
        fact_sections.append("MULTI-LOCATION DIRECTORY:\n" + _location_facts_block(locations))

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
        "4. If asked something not covered in BUSINESS FACTS, say you do not have that information and offer to have someone follow up.",
        "5. When BUSINESS FACTS lists multiple locations or coverage areas, mention all of them — do not omit any.",
        f"6. Use a {tone} tone. Keep answers concise and natural for phone calls.",
    ])

    if voice_level == "starter":
        parts.append(
            "STARTER TIER RULES:\n"
            "- Accept basic appointment requests only (name, contact, preferred time).\n"
            "- Do NOT ask follow-up questions beyond essentials.\n"
            "- Do NOT run workflows, lead-capture sequences, or call forwarding.\n"
            "- Use the default friendly personality."
        )
    elif voice_level == "pro":
        parts.append(
            "PRO TIER RULES:\n"
            "- Hold a full conversation with follow-up questions.\n"
            "- Collect detailed appointment requests and lead information.\n"
            "- Custom personality instructions from BUSINESS FACTS apply."
        )
        if allow_forwarding and getattr(settings, "call_forwarding_enabled", 0):
            forward_to = (getattr(settings, "call_forwarding_number", None) or "").strip()
            if forward_to:
                parts.append(
                    f"Call forwarding is enabled. If the caller asks for a person or urgent help, "
                    f"tell them you can connect them and note forwarding number {forward_to}."
                )
    elif voice_level == "premium" or is_premium:
        parts.append(
            "PREMIUM TIER RULES:\n"
            "- Full conversational AI with follow-ups, lead capture, and custom workflows.\n"
            "- Monthly optimization and dedicated support features are enabled for this account."
        )
        if allow_forwarding and getattr(settings, "call_forwarding_enabled", 0):
            forward_to = (getattr(settings, "call_forwarding_number", None) or "").strip()
            if forward_to:
                parts.append(
                    f"Default call forwarding number: {forward_to}."
                )

    if multi_enabled:
        parts.append(
            "MULTI-LOCATION FLOW:\n"
            '1. Early in the call, ask: "Which location are you calling about?"\n'
            "2. Match the caller's answer to a location in the MULTI-LOCATION DIRECTORY.\n"
            "3. After a location is chosen, use ONLY that location's hours, services, staff, "
            "knowledge, personality, and forwarding number.\n"
            "4. If forwarding is enabled for that location, use that location's forwarding number."
        )

    if not allow_follow_ups:
        parts.append("Do not ask probing follow-up questions. Keep the conversation brief.")

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
        logger.warning(
            "Voice instructions are very long (%s chars) for business_id=%s; "
            "consider shorter bullet points so all facts are followed reliably.",
            len(instructions),
            settings.business_id,
        )

    return instructions
