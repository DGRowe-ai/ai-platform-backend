from datetime import datetime
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from admin_analytics import get_admin_analytics
from auth_utils import get_current_user, require_platform_admin
from business_utils import delete_business_for_admin
from database import get_db
from email_utils import REPORT_RECIPIENT, send_email, send_email_with_attachment
from models import Business, Payment, ReportRun, User
from pdf_utils import build_monthly_report_pdf
from report_utils import (
    build_daily_report_data,
    build_monthly_report_data,
    format_daily_report_email,
    get_admin_businesses,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class PaymentRequest(BaseModel):
    business_id: str | None = None
    amount: float | None = None
    payment_date: str | None = None
    next_renewal_date: str | None = None
    note: str | None = None
    notes: str | None = None
    payment_type: str | None = None
    mark_paid: bool | None = None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").split("+")[0])
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None


def _get_business_by_key(db: Session, business_key: str) -> Business:
    business = db.query(Business).filter(Business.folder_name == business_key).first()
    if not business and business_key.isdigit():
        business = db.query(Business).filter(Business.id == int(business_key)).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _serialize_payment(payment: Payment, business: Business | None = None) -> dict:
    return {
        "id": payment.id,
        "business_id": business.folder_name if business else payment.business_id,
        "amount": payment.amount,
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
        "next_renewal_date": payment.next_renewal_date.isoformat() if payment.next_renewal_date else None,
        "payment_type": payment.payment_type,
        "note": payment.notes,
        "notes": payment.notes,
        "status": "paid",
    }


@router.get("/admin/analytics")
def admin_analytics(user=Depends(get_current_user)):
    require_platform_admin(user)
    return get_admin_analytics()


@router.get("/admin/businesses")
def admin_get_all_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    return get_admin_businesses(db)


@router.delete("/admin/businesses/{business_key}")
def admin_delete_business(
    business_key: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)

    try:
        result = delete_business_for_admin(db, business_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while deleting business_key=%s", business_key)
        raise HTTPException(status_code=500, detail="Unable to delete business")
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while deleting business_key=%s", business_key)
        raise HTTPException(status_code=500, detail="Unable to delete business")

    return result


@router.get("/admin/businesses/{business_key}/payments")
def list_business_payments(
    business_key: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    business = _get_business_by_key(db, business_key)
    payments = (
        db.query(Payment)
        .filter(Payment.business_id == business.id)
        .order_by(Payment.payment_date.desc())
        .all()
    )
    return {
        "payments": [_serialize_payment(payment, business) for payment in payments]
    }


@router.post("/admin/businesses/{business_key}/payments")
def record_business_payment(
    business_key: str,
    req: PaymentRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    business = _get_business_by_key(db, business_key)
    owner = db.query(User).filter(User.id == business.owner_id).first()

    if req.mark_paid and owner:
        owner.subscription_active = 1

    amount = req.amount if req.amount is not None else 29.99
    payment_date = _parse_date(req.payment_date) or datetime.utcnow()
    next_renewal = _parse_date(req.next_renewal_date)
    notes = req.note or req.notes or ""
    payment_type = req.payment_type or ("renewal" if req.mark_paid else "first_payment")

    payment = Payment(
        business_id=business.id,
        amount=amount,
        payment_date=payment_date,
        payment_type=payment_type,
        next_renewal_date=next_renewal,
        notes=notes,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return {
        "message": "Payment recorded",
        "payment": _serialize_payment(payment, business),
    }


@router.get("/admin/reports/daily-preview")
def daily_report_preview(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    return build_daily_report_data(db)


@router.post("/admin/reports/send-daily")
def send_daily_report(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    data = build_daily_report_data(db)
    subject, body = format_daily_report_email(data)
    recipient = REPORT_RECIPIENT

    try:
        send_email(recipient, subject, body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to send daily report email: {exc}")

    run = ReportRun(
        report_type="daily",
        recipient=recipient,
        status="sent",
        notes=f"Triggered by admin user {user.id}",
    )
    db.add(run)
    db.commit()

    return {
        "message": "Daily report sent",
        "recipient": recipient,
        "sent_at": run.sent_at.isoformat(),
        "preview": data,
    }


@router.get("/admin/reports/monthly.pdf")
def download_monthly_report_pdf(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    data = build_monthly_report_data(db, year=year, month=month)
    pdf_bytes = build_monthly_report_pdf(data)
    filename = f"rowe-ai-monthly-report-{data['year']}-{data['month']:02d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/reports/send-monthly")
def send_monthly_report(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    data = build_monthly_report_data(db, year=year, month=month)
    pdf_bytes = build_monthly_report_pdf(data)
    recipient = REPORT_RECIPIENT
    subject = f"Rowe AI Monthly Financial Summary - {data.get('month_label', '')}"
    body = (
        "Please find attached the Rowe AI Monthly Financial Summary Report.\n\n"
        "Rowe AI Business Manager"
    )
    filename = f"rowe-ai-monthly-report-{data['year']}-{data['month']:02d}.pdf"

    try:
        send_email_with_attachment(
            recipient,
            subject,
            body,
            pdf_bytes,
            filename,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to send monthly report email: {exc}")

    run = ReportRun(
        report_type="monthly",
        recipient=recipient,
        status="sent",
        notes=f"Triggered by admin user {user.id}",
    )
    db.add(run)
    db.commit()

    return {
        "message": "Monthly report sent",
        "recipient": recipient,
        "sent_at": run.sent_at.isoformat(),
        "month_label": data.get("month_label"),
    }


@router.get("/admin/reports/status")
def report_status(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_platform_admin(user)
    latest_daily = (
        db.query(ReportRun)
        .filter(ReportRun.report_type == "daily")
        .order_by(ReportRun.sent_at.desc())
        .first()
    )
    latest_monthly = (
        db.query(ReportRun)
        .filter(ReportRun.report_type == "monthly")
        .order_by(ReportRun.sent_at.desc())
        .first()
    )
    return {
        "recipient": REPORT_RECIPIENT,
        "last_daily_report": latest_daily.sent_at.isoformat() if latest_daily else None,
        "last_monthly_report": latest_monthly.sent_at.isoformat() if latest_monthly else None,
    }


@router.post("/internal/cron/daily-report")
def cron_daily_report(
    db: Session = Depends(get_db),
    cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
):
    expected = os.getenv("CRON_SECRET")
    if not expected or cron_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    data = build_daily_report_data(db)
    subject, body = format_daily_report_email(data)
    recipient = REPORT_RECIPIENT
    send_email(recipient, subject, body)

    run = ReportRun(
        report_type="daily",
        recipient=recipient,
        status="sent",
        notes="Scheduled cron job",
    )
    db.add(run)
    db.commit()

    return {"message": "Daily report sent", "recipient": recipient}
