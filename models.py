from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


# ============================
# USER MODEL (with RBAC)
# ============================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)

    # Password hash
    password_hash = Column(String)

    # Subscription status
    subscription_active = Column(Integer, default=0)

    # Possible values: "admin", "owner", "user"
    role = Column(String, default="owner")

    # Link to business (optional)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)

    # Relationship to businesses
    businesses = relationship(
        "Business",
        back_populates="owner",
        foreign_keys="Business.owner_id",
    )


# ============================
# BUSINESS MODEL
# ============================
class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    folder_name = Column(String, unique=True)

    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship(
        "User",
        back_populates="businesses",
        foreign_keys=[owner_id],
    )


# ============================
# CONVERSATIONS
# ============================
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))

    started_at = Column(String)
    last_message_at = Column(String)

    # Tags stored as comma-separated string
    tags = Column(String, default="")

    # Link to message logs
    messages = relationship("MessageLog", back_populates="conversation")


# ============================
# MESSAGE LOGS
# ============================
class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"))

    user_message = Column(Text)
    bot_response = Column(Text)

    # Store timestamp as ISO string
    timestamp = Column(String, default=lambda: datetime.utcnow().isoformat())

    business = relationship("Business")
    conversation = relationship("Conversation", back_populates="messages")


# ============================
# AUDIT LOGS
# ============================
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    event_type = Column(String(100))
    description = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


# ============================
# BUSINESS SETTINGS (Step 26)
# ============================
class BusinessSettings(Base):
    __tablename__ = "business_settings"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)

    greeting_message = Column(
        Text,
        default="Hello! How can I help you today?",
    )
    chatbot_tone = Column(
        String,
        default="friendly",  # friendly, professional, casual
    )
    max_response_length = Column(Integer, default=300)
    custom_instructions = Column(Text, default="")
    faq_items = Column(Text, default="")


# ============================
# CHAT MESSAGE LOG (Dashboard Chat)
# ============================
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    user_id = Column(Integer, index=True)
    role = Column(Text)  # "user" or "assistant"
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


# ============================
# RATE LIMIT TABLE (Step 6.2)
# ============================
class RateLimit(Base):
    __tablename__ = "rate_limits"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    ip_address = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
