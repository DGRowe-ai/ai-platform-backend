"""Appointment request collection, validation, storage, and client notifications."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from email_utils import send_appointment_confirmation_email, send_appointment_owner_notification
from models import AppointmentRequest, Business, BusinessSettings, User

logger = logging.getLogger(__name__)

APPOINTMENT_KNOWLEDGE_LINE = (
    "Customers can request appointments through the chatbot by telling it the "
    "date, time, and service they want."
)

APPOINTMENT_CHAT_INSTRUCTIONS = """
Appointment booking:
- When a customer wants to book an appointment, collect: full name, contact (email or phone),
  preferred date, preferred time, and the service they want. Notes are optional.
- Confirm the details with the customer before submitting.
- Once you have all required fields, call submit_appointment_request. Do not invent availability.
- If any detail is missing or unclear, ask for it instead of submitting.
"""

VALID_STATUSES = {"Pending", "Confirmed", "Rejected", "Done"}
DEFAULT_TIMEZONE = "America/Toronto"

APPOINTMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_appointment_request",
        "description": (
            "Submit a customer appointment request after collecting name, contact, "
            "date, time, and service."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer full name"},
                "customer_contact": {
                    "type": "string",
                    "description": "Customer email address or phone number",
                },
                "requested_date": {
                    "type": "string",
                    "description": "Preferred date in YYYY-MM-DD format",
                },
                "requested_time": {
                    "type": "string",
                    "description": "Preferred time, e.g. 14:30, 2:30 PM, or 2pm",
                },
                "service": {"type": "string", "description": "Requested service"},
                "notes": {"type": "string", "description": "Optional notes"},
            },
            "required": [
                "customer_name",
                "customer_contact",
                "requested_date",
                "requested_time",
                "service",
            ],
        },
    },
}


class AppointmentValidationError(ValueError):
    pass


def get_business_settings_row(db: Session, business_id: int) -> BusinessSettings:
    settings = db.query(BusinessSettings).filter_by(business_id=business_id).first()
    if not settings:
        settings = BusinessSettings(business_id=business_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def serialize_appointment_settings(settings: BusinessSettings) -> dict:
    return {
        "timezone": settings.business_timezone or DEFAULT_TIMEZONE,
        "notification_method": settings.appointment_notification_method or "email",
        "notification_email": settings.appointment_notification_email or "",
        "webhook_url": settings.appointment_webhook_url or "",
    }


def serialize_appointment(record: AppointmentRequest) -> dict:
    return {
        "id": record.id,
        "customer_name": record.customer_name,
        "customer_contact": record.customer_contact,
        "requested_date": record.requested_date,
        "requested_time": record.requested_time,
        "service": record.service,
        "notes": record.notes or "",
        "status": record.status,
        "timezone": record.timezone,
        "normalized_datetime": record.normalized_datetime,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _resolve_timezone(tz_name: str | None) -> ZoneInfo:
    candidate = (tz_name or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise AppointmentValidationError(
            f"Invalid business timezone configured: {candidate}"
        ) from exc


def _parse_time(value: str):
    cleaned = value.strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%H%M"):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", cleaned)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3)
        if meridiem == "PM" and hour < 12:
            hour += 12
        if meridiem == "AM" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
    raise AppointmentValidationError(
        "I couldn't understand that time. Please use a format like 2:30 PM or 14:30."
    )


def normalize_appointment_datetime(
    requested_date: str,
    requested_time: str,
    timezone_name: str | None,
) -> tuple[str, str, str]:
    tz = _resolve_timezone(timezone_name)
    date_text = requested_date.strip()
    try:
        parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise AppointmentValidationError(
            "Please provide the date in YYYY-MM-DD format (for example, 2026-07-15)."
        ) from exc

    parsed_time = _parse_time(requested_time)
    localized = datetime.combine(parsed_date, parsed_time, tzinfo=tz)
    now_local = datetime.now(tz)
    if localized <= now_local:
        raise AppointmentValidationError(
            "That date and time are in the past. Please choose a future appointment time."
        )

    return date_text, parsed_time.strftime("%H:%M"), localized.isoformat()


def validate_contact(contact: str) -> str:
    cleaned = contact.strip()
    if not cleaned:
        raise AppointmentValidationError("A contact email or phone number is required.")

    if "@" in cleaned:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned):
            raise AppointmentValidationError("Please provide a valid email address.")
        return cleaned.lower()

    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 10 or len(digits) > 15:
        raise AppointmentValidationError(
            "Please provide a valid phone number with 10 to 15 digits."
        )
    return cleaned


def validate_appointment_payload(payload: dict, timezone_name: str | None) -> dict:
    name = (payload.get("customer_name") or "").strip()
    service = (payload.get("service") or "").strip()
    notes = (payload.get("notes") or "").strip()

    if len(name) < 2:
        raise AppointmentValidationError("Please provide the customer's full name.")
    if len(service) < 2:
        raise AppointmentValidationError("Please tell us which service you would like.")

    contact = validate_contact(payload.get("customer_contact") or "")
    date_text, time_text, normalized = normalize_appointment_datetime(
        payload.get("requested_date") or "",
        payload.get("requested_time") or "",
        timezone_name,
    )

    return {
        "customer_name": name,
        "customer_contact": contact,
        "requested_date": date_text,
        "requested_time": time_text,
        "service": service,
        "notes": notes,
        "normalized_datetime": normalized,
        "timezone": timezone_name or DEFAULT_TIMEZONE,
    }


def get_owner_email(db: Session, business: Business) -> str | None:
    owner = db.query(User).filter(User.id == business.owner_id).first()
    return owner.email if owner else None


def notify_client_of_appointment(
    db: Session,
    business: Business,
    appointment: AppointmentRequest,
) -> None:
    settings = get_business_settings_row(db, business.id)
    method = (settings.appointment_notification_method or "email").strip().lower()

    if method in {"", "none", "off", "disabled"}:
        return

    payload = serialize_appointment(appointment)
    payload["business_name"] = business.name

    if method == "webhook":
        webhook_url = (settings.appointment_webhook_url or "").strip()
        if not webhook_url:
            logger.warning(
                "Webhook notification selected but no URL configured business_id=%s",
                business.id,
            )
            return
        try:
            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                logger.info(
                    "Appointment webhook delivered business_id=%s status=%s",
                    business.id,
                    response.status,
                )
        except (urllib.error.URLError, TimeoutError):
            logger.exception(
                "Failed to deliver appointment webhook business_id=%s",
                business.id,
            )
        return

    if method == "email":
        recipient = (settings.appointment_notification_email or "").strip()
        if not recipient:
            recipient = get_owner_email(db, business) or ""
        if not recipient:
            logger.warning(
                "No appointment notification email configured business_id=%s",
                business.id,
            )
            return
        try:
            send_appointment_owner_notification(
                to_email=recipient,
                business_name=business.name,
                appointment=payload,
            )
        except Exception:
            logger.exception(
                "Failed to send appointment owner email business_id=%s",
                business.id,
            )


def build_customer_confirmation(appointment: AppointmentRequest) -> str:
    when = appointment.normalized_datetime or f"{appointment.requested_date} {appointment.requested_time}"
    lines = [
        f"Thanks, {appointment.customer_name}! Your appointment request has been received.",
        f"Service: {appointment.service}",
        f"Requested time: {when} ({appointment.timezone})",
        "Status: Pending — the business will confirm soon.",
    ]
    if appointment.notes:
        lines.append(f"Notes: {appointment.notes}")
    return "\n".join(lines)


def create_appointment_request(
    db: Session,
    business: Business,
    payload: dict,
) -> AppointmentRequest:
    settings = get_business_settings_row(db, business.id)
    validated = validate_appointment_payload(
        payload,
        settings.business_timezone or DEFAULT_TIMEZONE,
    )

    record = AppointmentRequest(
        business_id=business.id,
        customer_name=validated["customer_name"],
        customer_contact=validated["customer_contact"],
        requested_date=validated["requested_date"],
        requested_time=validated["requested_time"],
        service=validated["service"],
        notes=validated["notes"],
        status="Pending",
        timezone=validated["timezone"],
        normalized_datetime=validated["normalized_datetime"],
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    notify_client_of_appointment(db, business, record)

    if "@" in record.customer_contact:
        try:
            send_appointment_confirmation_email(
                to_email=record.customer_contact,
                business_name=business.name,
                appointment=serialize_appointment(record),
            )
        except Exception:
            logger.exception(
                "Failed to send appointment confirmation email business_id=%s",
                business.id,
            )

    return record


def process_appointment_tool_call(
    db: Session,
    business: Business,
    arguments_json: str,
) -> str:
    try:
        payload = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return "I couldn't save that appointment request. Please try again."

    try:
        appointment = create_appointment_request(db, business, payload)
        return build_customer_confirmation(appointment)
    except AppointmentValidationError as exc:
        return str(exc)
    except Exception:
        logger.exception("Appointment submission failed business_id=%s", business.id)
        return "Something went wrong while saving your appointment request. Please try again."


def update_appointment_settings(db: Session, business_id: int, data: dict) -> dict:
    settings = get_business_settings_row(db, business_id)

    if "timezone" in data:
        tz_name = (data.get("timezone") or DEFAULT_TIMEZONE).strip()
        _resolve_timezone(tz_name)
        settings.business_timezone = tz_name

    if "notification_method" in data:
        method = (data.get("notification_method") or "email").strip().lower()
        if method not in {"none", "email", "webhook"}:
            raise HTTPException(status_code=400, detail="Invalid notification method")
        settings.appointment_notification_method = method

    if "notification_email" in data:
        settings.appointment_notification_email = (data.get("notification_email") or "").strip()

    if "webhook_url" in data:
        settings.appointment_webhook_url = (data.get("webhook_url") or "").strip()

    db.add(settings)
    db.commit()
    db.refresh(settings)
    return serialize_appointment_settings(settings)


def update_appointment_status(
    db: Session,
    business_id: int,
    appointment_id: int,
    status: str,
) -> dict:
    normalized_status = status.strip().capitalize()
    if normalized_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid appointment status")

    record = (
        db.query(AppointmentRequest)
        .filter(
            AppointmentRequest.id == appointment_id,
            AppointmentRequest.business_id == business_id,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Appointment request not found")

    record.status = normalized_status
    db.add(record)
    db.commit()
    db.refresh(record)
    return serialize_appointment(record)


def seed_appointment_knowledge(settings: BusinessSettings) -> None:
    instructions = settings.custom_instructions or ""
    if APPOINTMENT_KNOWLEDGE_LINE not in instructions:
        settings.custom_instructions = (
            f"{instructions.rstrip()}\n\n{APPOINTMENT_KNOWLEDGE_LINE}".strip()
        )


def ensure_business_knowledge_file(folder_name: str) -> None:
    from pathlib import Path

    kb_path = Path(__file__).resolve().parent / "businesses" / folder_name / "knowledge.txt"
    if not kb_path.exists():
        return
    content = kb_path.read_text(encoding="utf-8", errors="ignore")
    if APPOINTMENT_KNOWLEDGE_LINE in content:
        return
    kb_path.write_text(
        f"{content.rstrip()}\n\n{APPOINTMENT_KNOWLEDGE_LINE}\n",
        encoding="utf-8",
    )
