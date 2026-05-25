from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    subscription_active = Column(Integer, default=0)

    # Step 17 fields
    role = Column(String, default="owner")
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)

    # FIX: specify foreign_keys so SQLAlchemy knows which FK belongs to this relationship
    businesses = relationship(
        "Business",
        back_populates="owner",
        foreign_keys="Business.owner_id"
    )


class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    folder_name = Column(String, unique=True)

    owner_id = Column(Integer, ForeignKey("users.id"))

    # FIX: specify foreign_keys here too
    owner = relationship(
        "User",
        back_populates="businesses",
        foreign_keys=[owner_id]
    )


# ⭐ STEP 18 + STEP 19 — Conversation Sessions + Tags
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    started_at = Column(String)
    last_message_at = Column(String)

    # ⭐ NEW FOR STEP 19 — tags stored as comma-separated string
    tags = Column(String, default="")

    # Link to message logs
    messages = relationship("MessageLog", back_populates="conversation")


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"))

    # ⭐ FIXED FIELDS — matches your /chat code
    user_message = Column(Text)
    bot_response = Column(Text)

    # ⭐ FIXED: store timestamp as STRING, not DateTime
    timestamp = Column(String, default=lambda: datetime.utcnow().isoformat())

    business = relationship("Business")
    conversation = relationship("Conversation", back_populates="messages")
