from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, Float
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

    # Product plan: chatbot, voicebot, duo
    plan_type = Column(String, default="chatbot")

    # Stripe billing
    stripe_customer_id = Column(String, nullable=True, index=True)
    billing_status = Column(String, default="inactive")

    # Password reset
    password_reset_token_hash = Column(String, nullable=True, index=True)
    password_reset_expires_at = Column(DateTime, nullable=True)

    # Referral program
    referral_code = Column(String, unique=True, nullable=True, index=True)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    referral_count = Column(Integer, default=0)
    free_months_earned = Column(Integer, default=0)
    referral_conversion_rewarded = Column(Integer, default=0)

    # Possible values: "admin", "owner", "user"
    role = Column(String, default="owner")

    # Link to business (optional)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)

    # Client lifecycle
    registered_at = Column(DateTime, nullable=True)
    review_request_email_sent_at = Column(DateTime, nullable=True)

    voicebot_welcome_email_sent_at = Column(DateTime, nullable=True)
    duo_welcome_email_sent_at = Column(DateTime, nullable=True)

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
    phone = Column(String, nullable=True)

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
    business_timezone = Column(String, default="America/Toronto")
    appointment_notification_method = Column(String, default="email")
    appointment_notification_email = Column(String, nullable=True)
    appointment_webhook_url = Column(String, nullable=True)
    voice_tone = Column(String, default="friendly")
    voice_custom_instructions = Column(Text, default="")
    voice_spell_name = Column(Integer, default=0)
    voice_greeting = Column(Text, default="")
    voice_business_phone = Column(String, default="")


# ============================
# WIDGET CUSTOMIZATION
# ============================
class WidgetSettings(Base):
    __tablename__ = "widget_settings"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, unique=True, index=True)
    settings_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow)


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


# ============================
# PAYMENTS (manual + tracked)
# ============================
class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), index=True)
    amount = Column(Float, nullable=False, default=0.0)
    payment_date = Column(DateTime, default=datetime.utcnow)
    payment_type = Column(String, default="first_payment")
    next_renewal_date = Column(DateTime, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    business = relationship("Business")


# ============================
# REPORT RUN LOG
# ============================
class ReportRun(Base):
    __tablename__ = "report_runs"

    id = Column(Integer, primary_key=True, index=True)
    report_type = Column(String, index=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    recipient = Column(String)
    status = Column(String, default="sent")
    notes = Column(Text, default="")


# ============================
# KNOWLEDGE BASE FILES
# ============================
class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("businesses.id"), index=True)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    embeddings = relationship(
        "KnowledgeEmbedding",
        back_populates="file",
        cascade="all, delete-orphan",
    )


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("businesses.id"), index=True)
    file_id = Column(Integer, ForeignKey("knowledge_files.id"), index=True)
    chunk_text = Column(Text, nullable=False)
    embedding_vector = Column(Text, nullable=False)

    file = relationship("KnowledgeFile", back_populates="embeddings")


# ============================
# BILLING CHECKOUT SESSIONS (pre-signup)
# ============================
class BillingCheckoutSession(Base):
    __tablename__ = "billing_checkout_sessions"

    id = Column(Integer, primary_key=True, index=True)
    stripe_session_id = Column(String, unique=True, index=True, nullable=False)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    customer_email = Column(String, nullable=True, index=True)
    billing_status = Column(String, default="pending")
    used = Column(Integer, default=0)
    referral_code = Column(String, nullable=True, index=True)
    plan_type = Column(String, default="chatbot")
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================
# VOICE CALL LOGS
# ============================
class VoiceCallLog(Base):
    __tablename__ = "voice_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), index=True)
    call_sid = Column(String, index=True)
    caller_number = Column(String, nullable=True)
    transcript = Column(Text, default="")
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)


# ============================
# REFERRAL SIGNUP LOG (abuse prevention)
# ============================
class ReferralSignupLog(Base):
    __tablename__ = "referral_signup_logs"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String, nullable=True, index=True)
    referral_code = Column(String, nullable=True, index=True)
    referrer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    referred_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================
# TRIAL ENROLLMENT (abuse prevention, survives account deletion)
# ============================
class TrialEnrollment(Base):
    __tablename__ = "trial_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=True, index=True)
    phone = Column(String, nullable=True, index=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    card_fingerprint = Column(String, nullable=True, index=True)
    device_fingerprint = Column(String, nullable=True, index=True)
    ip_address = Column(String, nullable=True, index=True)
    stripe_session_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    trial_used = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================
# APPOINTMENT REQUESTS (client dashboard only)
# ============================
class AppointmentRequest(Base):
    __tablename__ = "appointment_requests"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), index=True)
    customer_name = Column(String, nullable=False)
    customer_contact = Column(String, nullable=False)
    requested_date = Column(String, nullable=False)
    requested_time = Column(String, nullable=False)
    service = Column(String, nullable=False)
    notes = Column(Text, default="")
    status = Column(String, default="Pending", index=True)
    timezone = Column(String, default="America/Toronto")
    normalized_datetime = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
