import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PAYMENTS_ROOT = Path(__file__).resolve().parent / "payments"
PAYMENTS_ROOT = Path(os.getenv("PAYMENTS_LOG_DIR", str(_DEFAULT_PAYMENTS_ROOT)))
LOG_FILENAME = "payments.log"


def business_name_to_payment_folder_name(business_name: str) -> str:
    """Convert a business name to a safe folder slug (lowercase, hyphens)."""
    slug = (business_name or "").strip().lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ValueError("Business name must contain at least one alphanumeric character")
    return slug


def _payment_log_path(business_name: str) -> Path:
    folder_name = business_name_to_payment_folder_name(business_name)
    return PAYMENTS_ROOT / folder_name / LOG_FILENAME


def initialize_payment_log(business_name: str) -> Path:
    """Create the client payments folder and empty log file if missing."""
    log_path = _payment_log_path(business_name)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    logger.info("Initialized payment log at %s", log_path)
    return log_path


def format_amount_cents(amount_cents: int, currency: str = "usd") -> str:
    amount = amount_cents / 100
    normalized_currency = (currency or "usd").lower()
    if normalized_currency == "usd":
        return f"${amount:.2f}"
    return f"{amount:.2f} {normalized_currency.upper()}"


def payment_description_from_invoice(invoice_data: dict) -> str:
    lines = (invoice_data.get("lines") or {}).get("data") or []
    if lines:
        line_description = (lines[0].get("description") or "").strip()
        if line_description:
            return line_description[:200]

    billing_reason = (invoice_data.get("billing_reason") or "").strip()
    reason_labels = {
        "subscription_cycle": "Monthly subscription",
        "subscription_create": "Subscription started",
        "subscription_update": "Subscription updated",
        "manual": "Manual invoice",
    }
    return reason_labels.get(billing_reason, "Payment received")


def append_payment_log(
    business_name: str,
    *,
    amount_cents: int,
    invoice_id: str,
    description: str,
    currency: str = "usd",
    paid_at: datetime | None = None,
) -> Path:
    """Append one payment record line to the client's payments.log file."""
    if not invoice_id:
        raise ValueError("invoice_id is required")

    log_path = _payment_log_path(business_name)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)

    timestamp = (paid_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    amount_text = format_amount_cents(amount_cents, currency)
    safe_description = " ".join((description or "Payment received").split())
    line = f"{timestamp} | {amount_text} | {invoice_id} | {safe_description}\n"

    with log_path.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(line)

    logger.info(
        "Appended payment log entry business=%s invoice_id=%s",
        business_name_to_payment_folder_name(business_name),
        invoice_id,
    )
    return log_path


async def initialize_payment_log_async(business_name: str) -> Path:
    return await asyncio.to_thread(initialize_payment_log, business_name)


async def append_payment_log_async(
    business_name: str,
    *,
    amount_cents: int,
    invoice_id: str,
    description: str,
    currency: str = "usd",
    paid_at: datetime | None = None,
) -> Path:
    return await asyncio.to_thread(
        append_payment_log,
        business_name,
        amount_cents=amount_cents,
        invoice_id=invoice_id,
        description=description,
        currency=currency,
        paid_at=paid_at,
    )


def _parse_payment_log_line(line: str) -> dict | None:
    stripped = (line or "").strip()
    if not stripped:
        return None

    parts = [part.strip() for part in stripped.split("|")]
    if len(parts) < 4:
        return {
            "raw": stripped,
            "date": None,
            "amount": None,
            "invoice_id": None,
            "description": stripped,
        }

    return {
        "date": parts[0] or None,
        "amount": parts[1] or None,
        "invoice_id": parts[2] or None,
        "description": parts[3] or None,
        "raw": stripped,
    }


def read_payment_log_entries(business_name: str) -> list[dict]:
    log_path = _payment_log_path(business_name)
    if not log_path.exists():
        return []

    entries: list[dict] = []
    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Unable to read payment log at %s", log_path)
        return []

    for line in content.splitlines():
        parsed = _parse_payment_log_line(line)
        if parsed:
            entries.append(parsed)
    return entries


def get_payment_log_metadata(business_name: str) -> dict:
    log_path = _payment_log_path(business_name)
    folder_name = business_name_to_payment_folder_name(business_name)
    entries = read_payment_log_entries(business_name)

    last_entry = entries[-1] if entries else None
    return {
        "payment_folder": folder_name,
        "log_path": str(log_path),
        "log_exists": log_path.exists(),
        "entry_count": len(entries),
        "last_payment_date": last_entry.get("date") if last_entry else None,
        "last_payment_amount": last_entry.get("amount") if last_entry else None,
    }
