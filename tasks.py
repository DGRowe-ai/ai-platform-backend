from datetime import datetime, timedelta
from .database import SessionLocal
from .models import Business
from .email_utils import send_email

def send_inactivity_alerts():
    db = SessionLocal()
    cutoff = datetime.utcnow() - timedelta(days=7)

    inactive = db.query(Business).filter(Business.last_active < cutoff).all()

    for biz in inactive:
        send_email(
            to_email=biz.owner_email,
            subject="We Miss You!",
            body="Your chatbot hasn't been used in a while. Log in to keep it active."
        )

    db.close()
