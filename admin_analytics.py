from datetime import datetime, timedelta
from database import SessionLocal
from models import User, Business, AuditLog


def get_admin_analytics():
    with SessionLocal() as db:

        # Total users
        total_users = db.query(User).count()

        # Active subscriptions (fixed field name)
        active_subscriptions = db.query(User).filter(
            User.subscription_active == 1
        ).count()

        # Monthly Recurring Revenue
        mrr = active_subscriptions * 29.99

        # Messages in last 24 hours
        last_24h = datetime.utcnow() - timedelta(hours=24)
        messages_last_24h = db.query(AuditLog).filter(
            AuditLog.event_type == "chatbot_message",
            AuditLog.timestamp >= last_24h
        ).count()

        # Recent logs
        recent_logs = db.query(AuditLog).order_by(
            AuditLog.timestamp.desc()
        ).limit(20).all()

        # Per-business usage
        business_usage = []
        businesses = db.query(Business).all()

        for biz in businesses:
            count = db.query(AuditLog).filter(
                AuditLog.user_id == biz.owner_id,
                AuditLog.event_type == "chatbot_message"
            ).count()

            business_usage.append({
                "business_name": biz.name,
                "owner_email": biz.owner.email if biz.owner else None,
                "messages_sent": count
            })

        return {
            "total_users": total_users,
            "active_subscriptions": active_subscriptions,
            "mrr": mrr,
            "messages_last_24h": messages_last_24h,
            "recent_logs": [
                {
                    "event_type": log.event_type,
                    "description": log.description,
                    "timestamp": log.timestamp.isoformat()
                }
                for log in recent_logs
            ],
            "business_usage": business_usage
        }
