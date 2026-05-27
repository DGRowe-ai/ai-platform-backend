from datetime import datetime
from database import SessionLocal
from models import AuditLog


def log_event(user_id: int, event_type: str, description: str):
    """
    Write an audit log entry for important system events.
    """
    with SessionLocal() as db:
        log = AuditLog(
            user_id=user_id,
            event_type=event_type,
            description=description,
            timestamp=datetime.utcnow()
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
