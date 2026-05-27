from .database import SessionLocal
from .models import ChatMessage

def save_message(business_id, user_id, role, message):
    db = SessionLocal()
    msg = ChatMessage(
        business_id=business_id,
        user_id=user_id,
        role=role,
        message=message
    )
    db.add(msg)
    db.commit()
    db.close()

def get_history(business_id, limit=50):
    db = SessionLocal()
    messages = db.query(ChatMessage) \
        .filter(ChatMessage.business_id == business_id) \
        .order_by(ChatMessage.timestamp.desc()) \
        .limit(limit) \
        .all()
    db.close()
    return list(reversed(messages))
