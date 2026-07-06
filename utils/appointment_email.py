"""Send appointment request notification emails to business owners."""

from __future__ import annotations

from email_utils import send_email


def _appointment_field(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def send_appointment_email(to_email: str, appointment_data: dict) -> None:
    recipient = (to_email or "").strip()
    if not recipient:
        return

    customer_name = _appointment_field(
        appointment_data,
        "customerName",
        "customer_name",
    )
    customer_phone = _appointment_field(
        appointment_data,
        "customerPhone",
        "customer_phone",
        "customer_contact",
    )
    requested_date = _appointment_field(
        appointment_data,
        "requestedDate",
        "requested_date",
    )
    requested_time = _appointment_field(
        appointment_data,
        "requestedTime",
        "requested_time",
    )
    service = _appointment_field(appointment_data, "service")
    notes = _appointment_field(appointment_data, "notes") or "None"

    when = _appointment_field(appointment_data, "normalized_datetime")
    if not when and requested_date and requested_time:
        when = f"{requested_date} {requested_time}"
    elif not when:
        when = "Not specified"

    body = f"""Hello,

You have a new appointment request.

Customer name: {customer_name}
Customer phone: {customer_phone}
Requested date/time: {when}
Service: {service}
Notes: {notes}

Log in to your client dashboard to confirm or reject this request.

Rowe AI
"""
    send_email(
        to_email=recipient,
        subject="New Appointment Request",
        body=body,
    )
