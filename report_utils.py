from datetime import datetime, timedelta
from calendar import monthrange

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    AuditLog,
    Business,
    ChatMessage,
    MessageLog,
    Payment,
    User,
)

SUBSCRIPTION_AMOUNT = 29.99
WARNING_EVENT_TYPES = {
    "payment_failed",
    "subscription_canceled",
    "server_error",
}


def _parse_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def _business_message_count(db: Session, business_id: int, since: datetime | None = None) -> int:
    msg_log_query = db.query(MessageLog).filter(MessageLog.business_id == business_id)
    chat_query = db.query(ChatMessage).filter(ChatMessage.business_id == business_id)

    if since:
        since_iso = since.isoformat()
        msg_log_query = msg_log_query.filter(MessageLog.timestamp >= since_iso)
        chat_query = chat_query.filter(ChatMessage.timestamp >= since)

    return msg_log_query.count() + chat_query.count()


def _business_has_chat_activity(db: Session, business_id: int) -> bool:
    if db.query(MessageLog).filter(MessageLog.business_id == business_id).first():
        return True
    if db.query(ChatMessage).filter(ChatMessage.business_id == business_id).first():
        return True
    return False


def _serialize_business_row(db: Session, business: Business) -> dict:
    owner = business.owner
    subscription_active = bool(owner.subscription_active) if owner else False
    last_payment = (
        db.query(Payment)
        .filter(Payment.business_id == business.id)
        .order_by(Payment.payment_date.desc())
        .first()
    )
    total_messages = _business_message_count(db, business.id)
    total_conversations = db.query(MessageLog).filter(
        MessageLog.business_id == business.id
    ).count()

    payment_status = "paid" if subscription_active else "overdue"
    if not subscription_active and not last_payment:
        payment_status = "none"

    return {
        "id": business.id,
        "business_id": business.folder_name,
        "folder_name": business.folder_name,
        "business_name": business.name,
        "name": business.name,
        "owner_email": owner.email if owner else None,
        "subscription_active": subscription_active,
        "subscription_status": "active" if subscription_active else "inactive",
        "payment_status": payment_status,
        "created_at": None,
        "last_payment": last_payment.payment_date.isoformat() if last_payment else None,
        "next_renewal": last_payment.next_renewal_date.isoformat() if last_payment and last_payment.next_renewal_date else None,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "chatbot_activated": _business_has_chat_activity(db, business.id),
        "messages_last_24h": _business_message_count(
            db, business.id, datetime.utcnow() - timedelta(hours=24)
        ),
    }


def get_admin_businesses(db: Session) -> list[dict]:
    businesses = db.query(Business).all()
    return [_serialize_business_row(db, business) for business in businesses]


def _recent_signups(db: Session, since: datetime) -> list[dict]:
    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type == "signup",
            AuditLog.timestamp >= since,
        )
        .order_by(AuditLog.timestamp.desc())
        .all()
    )
    output = []
    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        business = None
        if user:
            business = db.query(Business).filter(Business.owner_id == user.id).first()
        output.append({
            "user_id": log.user_id,
            "email": user.email if user else None,
            "business_name": business.name if business else None,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        })
    return output


def _warnings(db: Session, since: datetime) -> list[dict]:
    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type.in_(WARNING_EVENT_TYPES),
            AuditLog.timestamp >= since,
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "event_type": log.event_type,
            "description": log.description,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


def build_daily_report_data(db: Session) -> dict:
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)
    renewal_window_end = now + timedelta(days=7)

    businesses = db.query(Business).all()
    business_rows = [_serialize_business_row(db, business) for business in businesses]

    total_businesses = len(business_rows)
    new_signups = _recent_signups(db, since_24h)
    not_activated = [row for row in business_rows if not row["chatbot_activated"]]
    active_businesses = [
        row for row in business_rows
        if row["subscription_active"] and row["messages_last_24h"] > 0
    ]
    inactive_businesses = [
        row for row in business_rows if row["messages_last_24h"] == 0
    ]
    total_chats_24h = sum(row["messages_last_24h"] for row in business_rows)
    warnings = _warnings(db, since_24h)

    overdue_clients = [
        row for row in business_rows
        if row["payment_status"] == "overdue" or not row["subscription_active"]
    ]

    upcoming_renewals = []
    for row in business_rows:
        renewal = _parse_iso(row.get("next_renewal"))
        if renewal and now <= renewal <= renewal_window_end:
            upcoming_renewals.append({
                "business_name": row["business_name"],
                "owner_email": row["owner_email"],
                "renewal_date": renewal.date().isoformat(),
            })

    recommended_actions = []
    if overdue_clients:
        recommended_actions.append(
            f"Follow up with {len(overdue_clients)} overdue client(s) about payment."
        )
    if inactive_businesses:
        recommended_actions.append(
            f"Check in with {len(inactive_businesses)} inactive business(es) with no chat activity in the last 24 hours."
        )
    if warnings:
        recommended_actions.append(
            f"Review {len(warnings)} error or warning event(s) logged in the last 24 hours."
        )
    if new_signups:
        recommended_actions.append(
            f"Onboard {len(new_signups)} new signup(s) from the last 24 hours."
        )
    if not_activated:
        recommended_actions.append(
            f"Help {len(not_activated)} business(es) activate their chatbot."
        )
    if not recommended_actions:
        recommended_actions.append("No urgent actions required today.")

    return {
        "report_date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "summary_metrics": {
            "total_businesses_signed_up": total_businesses,
            "new_signups_last_24h": len(new_signups),
            "businesses_not_activated": len(not_activated),
            "active_businesses": len(active_businesses),
            "inactive_businesses": len(inactive_businesses),
            "total_chats_last_24h": total_chats_24h,
            "errors_or_warnings": len(warnings),
            "overdue_clients": len(overdue_clients),
            "upcoming_renewals_next_7_days": len(upcoming_renewals),
        },
        "new_signups": new_signups,
        "not_activated_businesses": [
            {
                "business_name": row["business_name"],
                "owner_email": row["owner_email"],
            }
            for row in not_activated
        ],
        "overdue_clients": [
            {
                "business_name": row["business_name"],
                "owner_email": row["owner_email"],
            }
            for row in overdue_clients
        ],
        "upcoming_renewals": upcoming_renewals,
        "warnings": warnings,
        "recommended_actions": recommended_actions,
    }


def format_daily_report_email(data: dict) -> tuple[str, str]:
    metrics = data.get("summary_metrics", {})
    subject = f"Rowe AI Daily Business Status Report - {data.get('report_date', 'Today')}"

    lines = [
        "Rowe AI Daily Business Status Report",
        f"Date: {data.get('report_date', 'No data provided.')}",
        "",
        "SUMMARY METRICS",
        f"- Total businesses signed up: {metrics.get('total_businesses_signed_up', 'No data provided.')}",
        f"- New signups in the last 24 hours: {metrics.get('new_signups_last_24h', 'No data provided.')}",
        f"- Businesses who have not activated their chatbot yet: {metrics.get('businesses_not_activated', 'No data provided.')}",
        f"- Active businesses: {metrics.get('active_businesses', 'No data provided.')}",
        f"- Inactive businesses (no chat activity): {metrics.get('inactive_businesses', 'No data provided.')}",
        f"- Total chats in the last 24 hours: {metrics.get('total_chats_last_24h', 'No data provided.')}",
        f"- Errors or warnings detected: {metrics.get('errors_or_warnings', 'No data provided.')}",
        f"- Overdue clients: {metrics.get('overdue_clients', 'No data provided.')}",
        f"- Upcoming renewals (next 7 days): {metrics.get('upcoming_renewals_next_7_days', 'No data provided.')}",
        "",
        "RECOMMENDED ACTIONS",
    ]

    for action in data.get("recommended_actions", []):
        lines.append(f"- {action}")

    if data.get("warnings"):
        lines.extend(["", "RECENT WARNINGS"])
        for warning in data["warnings"][:10]:
            lines.append(
                f"- {warning.get('event_type', 'warning')}: {warning.get('description', '')}"
            )

    if data.get("upcoming_renewals"):
        lines.extend(["", "UPCOMING RENEWALS"])
        for renewal in data["upcoming_renewals"]:
            lines.append(
                f"- {renewal.get('business_name', 'Unknown')} ({renewal.get('owner_email', 'No email')}) due {renewal.get('renewal_date', 'No data provided.')}"
            )

    lines.extend([
        "",
        "Rowe AI Business Manager",
    ])

    return subject, "\n".join(lines)


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def build_monthly_report_data(db: Session, year: int | None = None, month: int | None = None) -> dict:
    now = datetime.utcnow()
    year = year or now.year
    month = month or now.month
    month_start, month_end = _month_bounds(year, month)
    year_start = datetime(year, 1, 1)

    payments = (
        db.query(Payment)
        .filter(
            Payment.payment_date >= month_start,
            Payment.payment_date < month_end,
        )
        .order_by(Payment.payment_date.asc())
        .all()
    )

    payment_rows = []
    for payment in payments:
        business = db.query(Business).filter(Business.id == payment.business_id).first()
        payment_rows.append({
            "business_name": business.name if business else "Unknown",
            "payment_date": payment.payment_date.date().isoformat() if payment.payment_date else "No data provided.",
            "payment_amount": round(float(payment.amount or 0), 2),
            "payment_type": payment.payment_type or "No data provided.",
            "notes": payment.notes or "",
        })

    total_revenue = round(sum(row["payment_amount"] for row in payment_rows), 2)
    payment_count = len(payment_rows)

    if payment_rows:
        highest = max(payment_rows, key=lambda row: row["payment_amount"])
        lowest = min(payment_rows, key=lambda row: row["payment_amount"])
        average_payment = round(total_revenue / payment_count, 2)
    else:
        highest = lowest = None
        average_payment = 0.0

    new_clients = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type == "signup",
            AuditLog.timestamp >= month_start,
            AuditLog.timestamp < month_end,
        )
        .count()
    )

    lost_clients = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type == "subscription_canceled",
            AuditLog.timestamp >= month_start,
            AuditLog.timestamp < month_end,
        )
        .count()
    )

    overdue_revenue = round(
        db.query(Business)
        .join(User, Business.owner_id == User.id)
        .filter(User.subscription_active == 0)
        .count() * SUBSCRIPTION_AMOUNT,
        2,
    )

    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    next_month_start, next_month_end = _month_bounds(next_year, next_month)

    upcoming_renewals = (
        db.query(Payment)
        .filter(
            Payment.next_renewal_date.isnot(None),
            Payment.next_renewal_date >= next_month_start,
            Payment.next_renewal_date < next_month_end,
        )
        .count()
    )

    ytd_revenue = round(
        db.query(func.coalesce(func.sum(Payment.amount), 0.0))
        .filter(
            Payment.payment_date >= year_start,
            Payment.payment_date < month_end,
        )
        .scalar(),
        2,
    )

    return {
        "month_label": f"{month_start.strftime('%B %Y')}",
        "year": year,
        "month": month,
        "month_overview": {
            "total_revenue_collected": total_revenue,
            "payments_received": payment_count,
            "highest_paying_client": highest["business_name"] if highest else "No data provided.",
            "lowest_paying_client": lowest["business_name"] if lowest else "No data provided.",
            "average_payment_amount": average_payment,
            "new_clients_this_month": new_clients,
            "lost_clients": lost_clients,
        },
        "payment_table": payment_rows,
        "monthly_totals": {
            "total_revenue_for_month": total_revenue,
            "total_overdue_revenue": overdue_revenue,
            "total_upcoming_renewals_next_month": upcoming_renewals,
            "year_to_date_revenue": ytd_revenue,
        },
    }
