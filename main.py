from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Request,
    Header,
    Response,
    File,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from pydantic.config import ConfigDict
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from openai import OpenAI
import asyncio
import json
import os
import io
import zipfile
import stripe
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
DEPLOYMENT_VERSION = "appointment-requests-2026-06-26-1"

# -------------------------------------------------
# Load environment
# -------------------------------------------------
load_dotenv()

# -------------------------------------------------
# FastAPI app (enable docs)
# -------------------------------------------------
app = FastAPI(docs_url="/docs", redoc_url="/redoc")

# -------------------------------------------------
# CORS
# -------------------------------------------------
DEFAULT_CORS_ORIGINS = [
    "https://ai-platform-frontend-uaaa.onrender.com",
    "https://roweai.ca",
    "https://www.roweai.ca",
    "https://dgrowe-ai.github.io",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]


def get_cors_origins():
    configured_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
    configured = [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]
    # Merge env-configured origins with defaults so marketing/local dev origins
    # are not dropped when CORS_ALLOWED_ORIGINS is set on Render.
    merged: list[str] = []
    seen: set[str] = set()
    for origin in [*configured, *DEFAULT_CORS_ORIGINS]:
        if origin and origin not in seen:
            seen.add(origin)
            merged.append(origin)
    return merged

# -------------------------------------------------
# Database + models
# -------------------------------------------------
from database import Base, engine, SessionLocal, get_db
from models import User, Business, MessageLog, Conversation, Payment, ReportRun, KnowledgeFile, KnowledgeEmbedding, BillingCheckoutSession, WidgetSettings, AppointmentRequest, BusinessSettings, VoiceCallLog
Base.metadata.create_all(bind=engine)

# -------------------------------------------------
# Auth utilities
# -------------------------------------------------
from auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    parse_admin_emails,
    require_platform_admin,
    require_role,
    sync_admin_role_from_allowlist,
    user_is_platform_admin,
)

# -------------------------------------------------
# Business creation engine
# -------------------------------------------------
from business_utils import TEMPLATE_PATH, create_business_for_user

# -------------------------------------------------
# Audit + email + analytics utilities
# -------------------------------------------------
from audit_utils import log_event
from email_utils import (
    send_email,
    send_admin_registration_notification,
    send_admin_referral_conversion_email,
    send_referral_reward_email,
    send_referred_user_welcome_email,
    send_welcome_email_with_referral,
)
from admin_analytics import get_admin_analytics
from business_settings_utils import get_settings, update_settings
from knowledge_utils import (
    delete_knowledge_file,
    ingest_knowledge_file,
    list_knowledge_files,
    retrieve_knowledge_context,
)
from stripe_checkout_utils import (
    build_checkout_activation_url,
    create_billing_first_checkout_session,
    create_customer_portal_session,
    create_subscription_checkout_session,
    consume_checkout_session_for_signup,
    get_frontend_public_url,
    resolve_checkout_user,
    upsert_billing_checkout_session,
    verify_checkout_session_for_registration,
)
from referral_utils import (
    apply_referral_on_signup,
    build_referral_link,
    ensure_user_referral_code,
    get_referral_stats,
    process_referral_conversion,
)
from review_email_utils import backfill_registered_at_from_audit_logs
from payment_log_utils import (
    append_payment_log_async,
    get_payment_log_metadata,
    initialize_payment_log,
    payment_description_from_invoice,
    read_payment_log_entries,
)
from phone_utils import InvalidBusinessPhoneError, normalize_business_phone
from appointment_utils import (
    APPOINTMENT_CHAT_INSTRUCTIONS,
    APPOINTMENT_KNOWLEDGE_LINE,
    APPOINTMENT_TOOL,
    AppointmentValidationError,
    create_appointment_request,
    normalize_external_appointment_payload,
    process_appointment_tool_call,
    serialize_appointment,
    serialize_appointment_settings,
    update_appointment_settings,
    update_appointment_status,
)
from trial_protection_utils import (
    check_trial_eligibility,
    get_client_ip,
    process_checkout_trial_protection,
    record_trial_enrollment,
    strip_subscription_trial,
)
from plan_utils import (
    COUPON_ELIGIBLE_TIERS,
    PLAN_CHATBOT,
    PLAN_VOICEBOT,
    TIER_STARTER,
    apply_tier_to_user,
    dashboard_path_for_user,
    normalize_checkout_plan,
    normalize_plan_type,
    plan_type_from_stripe_price,
    require_appointment_notifications,
    require_basic_appointments,
    require_chatbot_access,
    require_duo_access,
    require_voicebot_access,
    serialize_subscription,
    tier_allows_appointment_followups,
    tier_allows_appointment_notifications,
    tier_allows_basic_appointments,
    tier_from_stripe_price,
    user_has_chatbot,
    user_has_voicebot,
    user_plan_type,
    user_product_type,
    user_tier,
)
from plan_welcome_email_utils import (
    send_product_welcome_emails_if_needed,
    should_send_chatbot_welcome_email,
)
from voice_settings_utils import get_voice_settings, record_voicebot_coupon_used, update_voice_settings
from voice_call_utils import delete_voice_call_history, get_voice_call_history
from voice_subscription_utils import cancel_voicebot_subscription

# -------------------------------------------------
# Stripe setup
# -------------------------------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# -------------------------------------------------
# OpenAI setup
# -------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------------------------------
# Database session dependency
# -------------------------------------------------
from database import get_db

# -------------------------------------------------
# Chat history utilities
# -------------------------------------------------
from chat_history_utils import save_message, get_history


def apply_admin_email_allowlist():
    admin_emails = parse_admin_emails()
    if not admin_emails:
        return

    logger.info("Loaded %s platform admin email(s) from ADMIN_EMAILS", len(admin_emails))


def backfill_billing_for_legacy_accounts():
    """Activate billing flags for admins and existing Stripe customers."""
    db = SessionLocal()
    try:
        updated = 0
        users = db.query(User).all()

        for user in users:
            should_activate = (
                user_is_platform_admin(user)
                or user.subscription_active
                or bool(user.stripe_customer_id)
            )
            if not should_activate:
                continue

            changed = False
            if (user.billing_status or "").strip().lower() != "active":
                user.billing_status = "active"
                changed = True
            if not user.subscription_active:
                user.subscription_active = 1
                changed = True
            if changed:
                updated += 1
                db.add(user)

        if updated:
            db.commit()
            logger.info("Backfilled active billing for %s user(s)", updated)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to backfill billing status for legacy accounts")
    finally:
        db.close()


def ensure_business_settings_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(business_settings)"))
        }

        if "max_response_length" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE business_settings "
                    "ADD COLUMN max_response_length INTEGER DEFAULT 300"
                )
            )

        if "faq_items" not in columns:
            connection.execute(
                text("ALTER TABLE business_settings ADD COLUMN faq_items TEXT DEFAULT ''")
            )

        if "business_timezone" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE business_settings "
                    "ADD COLUMN business_timezone TEXT DEFAULT 'America/Toronto'"
                )
            )

        if "appointment_notification_method" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE business_settings "
                    "ADD COLUMN appointment_notification_method TEXT DEFAULT 'email'"
                )
            )

        if "appointment_notification_email" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE business_settings "
                    "ADD COLUMN appointment_notification_email TEXT"
                )
            )

        if "appointment_webhook_url" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE business_settings "
                    "ADD COLUMN appointment_webhook_url TEXT"
                )
            )

        voice_columns = {
            ("voice_tone", "ADD COLUMN voice_tone TEXT DEFAULT 'friendly'"),
            ("voice_custom_instructions", "ADD COLUMN voice_custom_instructions TEXT DEFAULT ''"),
            ("voice_spell_name", "ADD COLUMN voice_spell_name INTEGER DEFAULT 0"),
            ("voice_greeting", "ADD COLUMN voice_greeting TEXT DEFAULT ''"),
            ("voice_business_phone", "ADD COLUMN voice_business_phone TEXT DEFAULT ''"),
            ("voice_business_name", "ADD COLUMN voice_business_name TEXT DEFAULT ''"),
            ("voice_coupon_used", "ADD COLUMN voice_coupon_used TEXT DEFAULT ''"),
            ("multi_location_enabled", "ADD COLUMN multi_location_enabled INTEGER DEFAULT 0"),
            ("locations_json", "ADD COLUMN locations_json TEXT DEFAULT '[]'"),
            ("call_forwarding_enabled", "ADD COLUMN call_forwarding_enabled INTEGER DEFAULT 0"),
            ("call_forwarding_number", "ADD COLUMN call_forwarding_number TEXT DEFAULT ''"),
            ("monthly_optimization", "ADD COLUMN monthly_optimization INTEGER DEFAULT 0"),
            ("dedicated_support", "ADD COLUMN dedicated_support INTEGER DEFAULT 0"),
            ("custom_workflows_json", "ADD COLUMN custom_workflows_json TEXT DEFAULT '[]'"),
        }
        for column_name, ddl in voice_columns:
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE business_settings {ddl}"))


def ensure_user_stripe_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)"))
        }

        if "stripe_customer_id" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
            )

        if "billing_status" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN billing_status TEXT DEFAULT 'inactive'")
            )

        if "password_reset_token_hash" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN password_reset_token_hash TEXT")
            )

        if "password_reset_expires_at" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN password_reset_expires_at TEXT")
            )

        if "referral_code" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN referral_code TEXT"))

        if "referred_by_user_id" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER"))

        if "referral_count" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
            )

        if "free_months_earned" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN free_months_earned INTEGER DEFAULT 0")
            )

        if "referral_conversion_rewarded" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN referral_conversion_rewarded INTEGER DEFAULT 0"
                )
            )

        if "registered_at" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN registered_at TEXT"))

        if "review_request_email_sent_at" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN review_request_email_sent_at TEXT")
            )

        if "plan_type" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN plan_type TEXT DEFAULT 'chatbot'")
            )

        if "product_type" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN product_type TEXT DEFAULT 'chatbot'")
            )

        if "tier" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN tier TEXT DEFAULT 'chatbot'")
            )

        if "voicebot_welcome_email_sent_at" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN voicebot_welcome_email_sent_at TEXT")
            )

        if "duo_welcome_email_sent_at" not in columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN duo_welcome_email_sent_at TEXT")
            )


def ensure_user_password_reset_schema():
    ensure_user_stripe_schema()


def ensure_referral_schema():
    ensure_user_password_reset_schema()

    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        checkout_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(billing_checkout_sessions)"))
        }
        if "referral_code" not in checkout_columns:
            connection.execute(
                text("ALTER TABLE billing_checkout_sessions ADD COLUMN referral_code TEXT")
            )
        if "plan_type" not in checkout_columns:
            connection.execute(
                text(
                    "ALTER TABLE billing_checkout_sessions "
                    "ADD COLUMN plan_type TEXT DEFAULT 'chatbot'"
                )
            )
        if "coupon_code" not in checkout_columns:
            connection.execute(
                text("ALTER TABLE billing_checkout_sessions ADD COLUMN coupon_code TEXT")
            )
        if "tier" not in checkout_columns:
            connection.execute(
                text(
                    "ALTER TABLE billing_checkout_sessions "
                    "ADD COLUMN tier TEXT DEFAULT 'chatbot'"
                )
            )
        if "product_type" not in checkout_columns:
            connection.execute(
                text(
                    "ALTER TABLE billing_checkout_sessions "
                    "ADD COLUMN product_type TEXT DEFAULT 'chatbot'"
                )
            )

        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS referral_signup_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT,
                    referral_code TEXT,
                    referrer_user_id INTEGER,
                    referred_user_id INTEGER,
                    created_at TEXT
                )
                """
            )
        )


def backfill_referral_codes():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.referral_code.is_(None)).all()
        updated = 0
        for user in users:
            ensure_user_referral_code(db, user)
            updated += 1
        if updated:
            logger.info("Backfilled referral codes for %s user(s)", updated)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to backfill referral codes")
    finally:
        db.close()


def backfill_registered_at_on_startup():
    db = SessionLocal()
    try:
        updated = backfill_registered_at_from_audit_logs(db)
        if updated:
            logger.info("Backfilled registered_at for %s user(s)", updated)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to backfill registered_at values")
    finally:
        db.close()


def ensure_billing_checkout_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS billing_checkout_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stripe_session_id TEXT UNIQUE NOT NULL,
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    customer_email TEXT,
                    billing_status TEXT DEFAULT 'pending',
                    used INTEGER DEFAULT 0,
                    created_at TEXT
                )
                """
            )
        )


def ensure_business_phone_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(businesses)"))
        }
        if "phone" not in columns:
            connection.execute(text("ALTER TABLE businesses ADD COLUMN phone TEXT"))


def ensure_widget_settings_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS widget_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_id INTEGER UNIQUE,
                    settings_json TEXT DEFAULT '{}',
                    updated_at TEXT
                )
                """
            )
        )


def ensure_trial_enrollment_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS trial_enrollments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT,
                    phone TEXT,
                    stripe_customer_id TEXT,
                    card_fingerprint TEXT,
                    device_fingerprint TEXT,
                    ip_address TEXT,
                    stripe_session_id TEXT,
                    stripe_subscription_id TEXT,
                    trial_used INTEGER DEFAULT 1,
                    created_at TEXT
                )
                """
            )
        )


def ensure_appointment_requests_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS appointment_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_id INTEGER NOT NULL,
                    customer_name TEXT NOT NULL,
                    customer_contact TEXT NOT NULL,
                    requested_date TEXT NOT NULL,
                    requested_time TEXT NOT NULL,
                    service TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    status TEXT DEFAULT 'Pending',
                    timezone TEXT DEFAULT 'America/Toronto',
                    normalized_datetime TEXT,
                    created_at TEXT
                )
                """
            )
        )


def ensure_voice_call_schema():
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS voice_call_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_id INTEGER NOT NULL,
                    call_sid TEXT,
                    caller_number TEXT,
                    transcript TEXT DEFAULT '',
                    started_at TEXT,
                    ended_at TEXT
                )
                """
            )
        )


def grant_complimentary_voicebot_access():
    db = SessionLocal()
    try:
        from plan_utils import COMPLIMENTARY_DUO_EMAILS, TIER_DUO_PREMIUM, apply_tier_to_user

        updated = 0
        for email in COMPLIMENTARY_DUO_EMAILS:
            user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
            if not user:
                logger.warning("Complimentary duo user not found: %s", email)
                continue
            apply_tier_to_user(user, TIER_DUO_PREMIUM)
            user.subscription_active = 1
            user.billing_status = "active"
            db.add(user)
            updated += 1
        if updated:
            db.commit()
            logger.info("Granted complimentary duo premium access to %s user(s)", updated)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to grant complimentary duo access")
    finally:
        db.close()


ensure_business_settings_schema()
ensure_user_password_reset_schema()
ensure_referral_schema()
ensure_billing_checkout_schema()
ensure_business_phone_schema()
ensure_widget_settings_schema()
ensure_trial_enrollment_schema()
ensure_appointment_requests_schema()
ensure_voice_call_schema()
apply_admin_email_allowlist()
backfill_billing_for_legacy_accounts()
backfill_referral_codes()
backfill_registered_at_on_startup()
grant_complimentary_voicebot_access()

# -------------------------------------------------
# Request models
# -------------------------------------------------
class CreateBusinessRequest(BaseModel):
    owner_id: int
    business_name: str

class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None

class PublicChatRequest(BaseModel):
    business_id: str
    message: str

class ClientChatRequest(BaseModel):
    message: str
    client_id: int | None = None

class SignupRequest(BaseModel):
    email: str
    password: str
    business_name: str
    business_phone: str
    session_id: str
    referral_code: str | None = None
    device_fingerprint: str | None = None

    @field_validator("business_phone")
    @classmethod
    def validate_business_phone_field(cls, value: str) -> str:
        try:
            return normalize_business_phone(value)
        except InvalidBusinessPhoneError as exc:
            raise ValueError(str(exc)) from exc

class CreateCheckoutSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    referral_code: str | None = None
    device_fingerprint: str | None = None
    plan_type: str | None = "chatbot"
    tier: str | None = None
    coupon_code: str | None = Field(default=None, alias="couponCode")

class LoginRequest(BaseModel):
    email: str
    password: str

class InviteRequest(BaseModel):
    email: str
    role: str  # "admin" or "staff"

class SetPasswordRequest(BaseModel):
    user_id: int
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UpdateBusinessRequest(BaseModel):
    folder_name: str
    name: str
    industry: str
    contact_email: str
    website: str
    tone: str
    greeting: str
    instructions: str
    knowledge: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str):
    normalized_email = normalize_email(email)
    try:
        return db.query(User).filter(func.lower(User.email) == normalized_email).first()
    except SQLAlchemyError:
        logger.exception("Database error while looking up user during login")
        raise HTTPException(status_code=500, detail="Unable to complete login")


def serialize_business_summary(business):
    try:
        business_id = business.id
        name = business.name
        folder_name = business.folder_name
    except Exception:
        logger.exception("Unable to serialize business row")
        return None

    if business_id is None:
        logger.warning("Skipping business row with missing id")
        return None

    return {
        "id": business_id,
        "name": name or folder_name or "Untitled business",
        "folder_name": folder_name,
    }


def get_business_summaries_for_user(
    db: Session,
    user_id: int,
    *,
    fail_on_error: bool = True,
):
    try:
        businesses = db.query(Business).filter(Business.owner_id == user_id).all()
    except SQLAlchemyError:
        logger.exception("Database error while loading businesses for user_id=%s", user_id)
        if fail_on_error:
            raise HTTPException(status_code=500, detail="Unable to load businesses")
        return []

    summaries = []
    for business in businesses:
        summary = serialize_business_summary(business)
        if summary is not None:
            summaries.append(summary)

    return summaries


# -------------------------------------------------
# Guards
# -------------------------------------------------
def require_subscription(user: User = Depends(get_current_user)):
    billing_status = (user.billing_status or "inactive").strip().lower()
    if billing_status == "suspended":
        raise HTTPException(
            status_code=402,
            detail="Your account is suspended due to non-payment. Please update your billing to reactivate.",
        )
    if not user.subscription_active:
        raise HTTPException(status_code=402, detail="Subscription required")
    return user

def require_role_guard(user: User, allowed_roles: list[str]):
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Not authorized")


def get_login_role_for_client(user: User) -> str:
    """Return a client-safe role for login responses.

    Never emit ``admin`` here: the frontend regular login page treats that as a
    platform-admin redirect signal. Platform admins are identified separately via
    ``is_platform_admin`` and must use the dedicated admin login flow.
    """
    role = (user.role or "owner").strip().lower()
    if role == "admin" and not user_is_platform_admin(user):
        return "business_admin"

    if role == "admin":
        return "owner"

    return role

# -------------------------------------------------
# Analytics helper
# -------------------------------------------------
def count_messages_this_month(db: Session, business_id: int) -> int:
    now = datetime.utcnow()

    # Start of the current month
    month_start = datetime(now.year, now.month, 1)

    # Start of the next month (handles December correctly)
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1)
    else:
        month_end = datetime(now.year, now.month + 1, 1)

    return (
        db.query(MessageLog)
        .filter(
            MessageLog.business_id == business_id,
            MessageLog.timestamp >= month_start.isoformat(),
            MessageLog.timestamp < month_end.isoformat(),
        )
        .count()
    )

# -------------------------------------------------
# Health check
# -------------------------------------------------
@app.get("/")
def health_check():
    return {"status": "ok"}

@app.head("/")
def health_check_head():
    return Response(status_code=200)

# -------------------------------------------------
# Global exception handler
# -------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    try:
        log_event(
            user_id=None,
            event_type="server_error",
            description=str(exc),
        )
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}")

    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong. Please try again."},
    )


# -------------------------------------------------
# LOGIN ROUTE
# -------------------------------------------------
@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    password_is_valid = False
    try:
        password_is_valid = verify_password(req.password, user.password_hash)
    except Exception:
        logger.exception("Password verification failed for user_id=%s", user.id)

    if not password_is_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = sync_admin_role_from_allowlist(db, user)

    user_id = user.id
    business_role = (user.role or "owner").strip().lower()
    role = get_login_role_for_client(user)
    is_platform_admin = user_is_platform_admin(user)
    subscription_active = user.subscription_active
    business_id = user.business_id
    businesses = get_business_summaries_for_user(db, user_id, fail_on_error=False)

    token = create_access_token({
        "user_id": user_id,
        "role": role,
        "business_role": business_role,
        "account_role": business_role,
        "is_platform_admin": is_platform_admin,
        "subscription_active": subscription_active,
        "business_id": business_id
    })

    subscription = serialize_subscription(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "subscription_active": subscription_active,
        "plan_type": subscription["plan_type"],
        "product_type": subscription["product_type"],
        "tier": subscription["tier"],
        "has_chatbot": subscription["has_chatbot"],
        "has_voicebot": subscription["has_voicebot"],
        "complimentary": subscription.get("complimentary", False),
        "dashboard_url": subscription["dashboard_url"],
        "features": subscription["features"],
        "role": role,
        "business_role": business_role,
        "account_role": business_role,
        "is_platform_admin": is_platform_admin,
        "business_id": business_id,
        "businesses": businesses,
    }

# -------------------------------------------------
# REGISTER ROUTE
# -------------------------------------------------
@app.post("/register")
def register(req: LoginRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    new_user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        role="owner",
        subscription_active=0,
        billing_status="inactive",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User created", "user_id": new_user.id}

# -------------------------------------------------
# Routers
# -------------------------------------------------
from accounting_routes import router as accounting_router
from directory_routes import router as directory_router
from widget_routes import router as widget_router
from review_routes import router as review_router
from admin_routes import router as admin_router
from auth_routes import router as auth_router
from account_routes import router as account_router
from business_settings_routes import router as business_settings_router
from demo_routes import router as demo_router
app.include_router(admin_router)
app.include_router(accounting_router)
app.include_router(directory_router)
app.include_router(widget_router)
app.include_router(review_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(business_settings_router)
app.include_router(demo_router)

# -------------------------------------------------
# SHARED CHAT EXECUTION HELPER
# -------------------------------------------------
def resolve_business(db: Session, business_id):
    if business_id is None:
        return None

    if isinstance(business_id, int):
        return db.query(Business).filter(Business.id == business_id).first()

    business_key = str(business_id)
    if business_key.isdigit():
        business = db.query(Business).filter(Business.id == int(business_key)).first()
        if business:
            return business

    return db.query(Business).filter(Business.folder_name == business_key).first()


DEMO_BUSINESS_FOLDERS = frozenset({"rowe_ai", "rowe_ai_website"})


def require_business_billing_active(db: Session, business: Business):
    if business.folder_name in DEMO_BUSINESS_FOLDERS:
        return

    owner = db.query(User).filter(User.id == business.owner_id).first()
    if not owner:
        return

    billing_status = (owner.billing_status or "inactive").strip().lower()
    if billing_status == "suspended":
        raise HTTPException(
            status_code=402,
            detail=(
                "This chatbot has been suspended due to non-payment. "
                "Please update your billing to reactivate."
            ),
        )

    if user_is_platform_admin(owner):
        return

    if billing_status == "active" or owner.subscription_active:
        return

    if owner.stripe_customer_id:
        return

    raise HTTPException(
        status_code=402,
        detail="Your chatbot is not activated yet. Please complete your billing setup.",
    )


def get_business_owner(db: Session, business: Business):
    if not business.owner_id:
        return None
    return db.query(User).filter(User.id == business.owner_id).first()


def business_tier_allows_basic_appointments(db: Session, business: Business) -> bool:
    owner = get_business_owner(db, business)
    if not owner:
        return False
    return tier_allows_basic_appointments(user_tier(owner))


def business_tier_allows_appointment_notifications(db: Session, business: Business) -> bool:
    owner = get_business_owner(db, business)
    if not owner:
        return False
    return tier_allows_appointment_notifications(user_tier(owner))


def get_appointment_prompt_for_owner(owner: User | None) -> str:
    if not owner or not tier_allows_basic_appointments(user_tier(owner)):
        return ""

    if not tier_allows_appointment_followups(user_tier(owner)):
        return """
Appointment requests:
- If a customer asks for an appointment, collect only the basics: full name, contact
  email or phone, preferred date, preferred time, and requested service. Notes are optional.
- Ask only for missing required appointment fields. Do not ask extra follow-up questions.
- Once the required fields are present, call submit_appointment_request.
"""

    return APPOINTMENT_CHAT_INSTRUCTIONS


def _execute_chat(
    business_id: str,
    message: str,
    db: Session,
    conversation_id: int | None = None,
):
    business = resolve_business(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    require_business_billing_active(db, business)

    settings = get_settings(business.id)
    faq_items = settings.get("faqs", [])
    faq_text = "\n".join(
        f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}"
        for item in faq_items
        if isinstance(item, dict)
    )

    kb_context = retrieve_knowledge_context(db, business.id, message)
    legacy_kb = ""
    kb_path = Path(__file__).parent / "businesses" / business.folder_name / "knowledge.txt"
    if kb_path.exists():
        legacy_kb = kb_path.read_text(encoding="utf-8", errors="ignore").strip()

    owner = get_business_owner(db, business)
    appointment_prompt = get_appointment_prompt_for_owner(owner)

    system_prompt = f"""
    You are a chatbot for this business.
    Tone: {settings.get('tone', 'friendly')}
    Welcome message: {settings.get('welcome_message', 'Hello! How can I help you today?')}
    Custom instructions: {settings.get('custom_instructions', '')}
    Frequently asked questions:
    {faq_text or 'No FAQs configured.'}
    {appointment_prompt}
    """

    if kb_context:
        system_prompt += f"\nRelevant uploaded knowledge:\n{kb_context}"
    if legacy_kb:
        system_prompt += f"\nAdditional business knowledge:\n{legacy_kb[:4000]}"
    if appointment_prompt and APPOINTMENT_KNOWLEDGE_LINE not in system_prompt:
        system_prompt += f"\n{APPOINTMENT_KNOWLEDGE_LINE}"

    save_message(business.id, conversation_id, "user", message)
    history = get_history(business.id)

    conversation = [{"role": "system", "content": system_prompt}]
    for msg in history:
        conversation.append({"role": msg.role, "content": msg.message})
    conversation.append({"role": "user", "content": message})

    completion_kwargs = {
        "model": "gpt-4o-mini",
        "messages": conversation,
        "max_tokens": settings.get("max_response_length", 300),
        "timeout": 15,
    }
    if appointment_prompt:
        completion_kwargs.update(
            {
                "tools": [APPOINTMENT_TOOL],
                "tool_choice": "auto",
            }
        )

    response = client.chat.completions.create(
        **completion_kwargs,
    )

    assistant_message = response.choices[0].message
    if assistant_message.tool_calls:
        tool_call = assistant_message.tool_calls[0]
        if tool_call.function.name == "submit_appointment_request":
            bot_reply = process_appointment_tool_call(
                db,
                business,
                tool_call.function.arguments,
                notify_client=business_tier_allows_appointment_notifications(db, business),
            )
        else:
            bot_reply = assistant_message.content or "How can I help you today?"
    else:
        bot_reply = assistant_message.content or "How can I help you today?"
    save_message(business.id, conversation_id, "assistant", bot_reply)

    return bot_reply


# -------------------------------------------------
# DASHBOARD CHAT ROUTE (FIXED)
# -------------------------------------------------
@app.post("/chat")
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not request.message or request.message.strip() == "":
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    bot_reply = _execute_chat(
        business_id=current_user.business_id,
        message=request.message,
        db=db,
        conversation_id=request.conversation_id,
    )

    return {"response": bot_reply}

# -------------------------------------------------
# BUSINESS CHAT HISTORY ROUTE
# -------------------------------------------------
@app.post("/business/chat")
def public_business_chat(
    request: PublicChatRequest,
    db: Session = Depends(get_db),
):
    if not request.message or request.message.strip() == "":
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    bot_reply = _execute_chat(
        business_id=request.business_id,
        message=request.message,
        db=db,
        conversation_id=None,
    )

    return {"response": bot_reply}

# -------------------------------------------------
# SAVE CONVERSATION ROUTE
# -------------------------------------------------
@app.post("/save_conversation")
def save_conversation(
    request: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ["owner", "admin", "staff"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    title = request.get("title")
    summary = request.get("summary")

    if not title or not summary:
        raise HTTPException(status_code=400, detail="Missing title or summary")

    convo = Conversation(
        business_id=user.business_id,
        user_id=user.id,
        title=title,
        summary=summary,
        created_at=datetime.utcnow().isoformat(),
    )

    db.add(convo)
    db.commit()
    db.refresh(convo)

    return {"conversation_id": convo.id, "status": "saved"}

# -------------------------------------------------
# DELETE CONVERSATION ROUTE
# -------------------------------------------------
@app.delete("/delete_conversation/{convo_id}")
def delete_conversation(
    convo_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convo = (
        db.query(Conversation)
        .filter(
            Conversation.id == convo_id,
            Conversation.business_id == user.business_id,
        )
        .first()
    )

    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if user.role == "staff" and convo.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.delete(convo)
    db.commit()

    return {"status": "deleted", "conversation_id": convo_id}

# -------------------------------------------------
# Load business data from filesystem
# -------------------------------------------------
def load_business_data(business_id: str):
    base = Path(__file__).parent / "businesses" / business_id
    profile = json.loads((base / "profile.json").read_text())
    settings = json.loads((base / "settings.json").read_text())
    knowledge = (base / "knowledge.txt").read_text()
    return {"profile": profile, "settings": settings, "knowledge": knowledge}

# -------------------------------------------------
# Basic routes
# -------------------------------------------------
@app.get("/ping")
def ping():
    return {"message": "pong"}


@app.get("/deployment_version")
def deployment_version():
    return {
        "version": DEPLOYMENT_VERSION,
        "template_path": str(TEMPLATE_PATH),
    }

@app.get("/my_businesses")
def my_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)

    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")

    return get_business_summaries_for_user(db, user.id)


def get_client_business(db: Session, user: User):
    business = None

    if user.business_id:
        business = db.query(Business).filter(Business.id == user.business_id).first()

    if not business and user.role == "owner":
        business = db.query(Business).filter(Business.owner_id == user.id).first()

    if not business:
        business = db.query(Business).filter(Business.owner_id == user.id).first()

    if not business:
        raise HTTPException(
            status_code=404,
            detail=(
                "No business is linked to this account. "
                "Use your client business login, or contact support to link a business."
            ),
        )

    if user.role == "owner" and business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return business


def serialize_message_log(log: MessageLog):
    return {
        "id": log.id,
        "conversation_id": log.conversation_id,
        "timestamp": log.timestamp,
        "user_message": log.user_message,
        "bot_response": log.bot_response,
    }


@app.get("/client/dashboard")
def client_dashboard(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_chatbot_access(user)
    business = get_client_business(db, user)
    since = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    total_conversations = (
        db.query(Conversation)
        .filter(Conversation.business_id == business.id)
        .count()
    )
    total_messages = (
        db.query(MessageLog)
        .filter(MessageLog.business_id == business.id)
        .count()
    )
    messages_last_24h = (
        db.query(MessageLog)
        .filter(
            MessageLog.business_id == business.id,
            MessageLog.timestamp >= since,
        )
        .count()
    )
    latest_message_at = (
        db.query(func.max(MessageLog.timestamp))
        .filter(MessageLog.business_id == business.id)
        .scalar()
    )

    return {
        "business": {
            "id": business.id,
            "name": business.name,
            "folder_name": business.folder_name,
            "phone": business.phone,
        },
        "analytics": {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "messages_last_24h": messages_last_24h,
            "latest_message_at": latest_message_at,
        },
    }


@app.get("/client/chat_history")
def client_chat_history(
    limit: int = 50,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    safe_limit = min(max(limit, 1), 200)
    logs = (
        db.query(MessageLog)
        .filter(MessageLog.business_id == business.id)
        .order_by(MessageLog.timestamp.desc())
        .limit(safe_limit)
        .all()
    )
    return {
        "business_id": business.id,
        "messages": [serialize_message_log(log) for log in logs],
    }


@app.get("/client/payment_history")
async def client_payment_history(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)

    try:
        entries = await asyncio.to_thread(read_payment_log_entries, business.name)
        metadata = await asyncio.to_thread(get_payment_log_metadata, business.name)
    except Exception:
        logger.exception(
            "Failed to read client payment history business_id=%s user_id=%s",
            business.id,
            user.id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to load payment history right now.",
        )

    return {
        "business": {
            "id": business.id,
            "name": business.name,
            "folder_name": business.folder_name,
        },
        "payment_log_exists": metadata["log_exists"],
        "entries": list(reversed(entries)),
    }


@app.delete("/client/chat_history/{message_id}")
def delete_client_message(
    message_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    log = (
        db.query(MessageLog)
        .filter(
            MessageLog.id == message_id,
            MessageLog.business_id == business.id,
        )
        .first()
    )

    if not log:
        raise HTTPException(status_code=404, detail="Message not found")

    db.delete(log)
    db.commit()
    return {"status": "deleted", "message_id": message_id}


@app.delete("/client/conversations/{conversation_id}")
def delete_client_conversation(
    conversation_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.business_id == business.id,
        )
        .first()
    )

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.query(MessageLog).filter(
        MessageLog.conversation_id == conversation_id,
        MessageLog.business_id == business.id,
    ).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}


@app.get("/client/chatbot_settings")
def get_client_chatbot_settings(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    return get_settings(business.id)


@app.post("/client/chatbot_settings")
def save_client_chatbot_settings(
    data: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    return update_settings(business.id, data)


@app.get("/client/appointment_requests")
def list_client_appointment_requests(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_basic_appointments(user)
    business = get_client_business(db, user)
    records = (
        db.query(AppointmentRequest)
        .filter(AppointmentRequest.business_id == business.id)
        .order_by(AppointmentRequest.created_at.desc())
        .all()
    )
    return {
        "business_id": business.id,
        "requests": [serialize_appointment(record) for record in records],
    }


@app.patch("/client/appointment_requests/{appointment_id}")
def patch_client_appointment_request(
    appointment_id: int,
    data: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_basic_appointments(user)
    business = get_client_business(db, user)
    status = data.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status is required")
    return update_appointment_status(db, business.id, appointment_id, status)


@app.get("/client/appointment_settings")
def get_client_appointment_settings(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_appointment_notifications(user)
    business = get_client_business(db, user)
    settings = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == business.id)
        .first()
    )
    if not settings:
        return serialize_appointment_settings(BusinessSettings(business_id=business.id))
    return serialize_appointment_settings(settings)


@app.post("/client/appointment_settings")
def save_client_appointment_settings(
    data: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_appointment_notifications(user)
    business = get_client_business(db, user)
    return update_appointment_settings(db, business.id, data)


@app.post("/voicebot/appointment_requests")
def create_voicebot_appointment_request(
    data: dict,
    db: Session = Depends(get_db),
):
    business_key = data.get("businessId") or data.get("business_id")
    if not business_key:
        raise HTTPException(status_code=400, detail="businessId is required")

    business = resolve_business(db, business_key)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    if not business_tier_allows_basic_appointments(db, business):
        raise HTTPException(
            status_code=403,
            detail="This business subscription tier does not include appointment requests.",
        )

    payload = normalize_external_appointment_payload(data)
    try:
        record = create_appointment_request(
            db,
            business,
            payload,
            notify_client=business_tier_allows_appointment_notifications(db, business),
        )
    except AppointmentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "created",
        "appointment": serialize_appointment(record),
    }


@app.post("/client/change_password")
def change_client_password(
    req: ChangePasswordRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner"])

    if len(req.new_password.strip()) < 8:
        raise HTTPException(
            status_code=400,
            detail="New password must be at least 8 characters",
        )

    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    try:
        user.password_hash = hash_password(req.new_password)
        db.add(user)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while changing password for user_id=%s", user.id)
        raise HTTPException(status_code=500, detail="Unable to update password")

    return {"message": "Password updated successfully"}


@app.get("/client/referral-stats")
def client_referral_stats(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner"])
    return get_referral_stats(db, user)


@app.get("/client/subscription")
def client_subscription(
    user=Depends(get_current_user),
):
    require_subscription(user)
    return serialize_subscription(user)


@app.get("/client/voicebot/dashboard")
def client_voicebot_dashboard(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    calls = get_voice_call_history(business.id, limit=100)
    return {
        "business": {
            "id": business.id,
            "name": business.name,
            "folder_name": business.folder_name,
            "phone": business.phone,
        },
        "subscription": serialize_subscription(user),
        "analytics": {
            "total_calls": len(calls),
            "latest_call_at": calls[0]["started_at"] if calls else None,
        },
    }


@app.get("/client/voicebot_settings")
def get_client_voicebot_settings(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    return get_voice_settings(business.id)


@app.post("/client/voicebot_settings")
def save_client_voicebot_settings(
    data: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    try:
        return update_voice_settings(business.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/voicebot/settings")
def get_voicebot_settings(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    return get_voice_settings(business.id)


@app.post("/voicebot/settings")
def save_voicebot_settings(
    data: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    try:
        return update_voice_settings(business.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/client/voice_call_history")
def client_voice_call_history(
    limit: int = 50,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    return {
        "business_id": business.id,
        "calls": get_voice_call_history(business.id, limit=limit),
    }


@app.delete("/client/voice_call_history")
def delete_client_voice_call_history(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "owner" and not user_is_platform_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized")
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    business = get_client_business(db, user)
    deleted = delete_voice_call_history(business.id)
    return {"status": "deleted", "deleted_count": deleted}


@app.post("/client/voicebot/cancel")
def cancel_client_voicebot_service(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "owner" and not user_is_platform_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized")
    require_subscription(user)
    if not user_is_platform_admin(user):
        require_voicebot_access(user)
    return cancel_voicebot_subscription(db, user)


@app.post("/create-customer-portal-session")
def create_customer_portal_session_endpoint(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "owner" and not user_is_platform_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized")
    portal_url = create_customer_portal_session(db, user)
    return {"url": portal_url}


@app.post("/api/knowledge/upload")
async def upload_knowledge_file(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    record = await ingest_knowledge_file(db, business, file)
    return {"message": "File uploaded successfully", "file": record}


@app.get("/api/knowledge/list")
def get_knowledge_files(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    files = list_knowledge_files(db, business.id)
    return {"files": files}


@app.delete("/api/knowledge/delete/{file_id}")
def remove_knowledge_file(
    file_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)
    return delete_knowledge_file(db, business, file_id)


MAX_CLIENT_CHAT_MESSAGE_LENGTH = 2000


@app.post("/api/chat")
def client_test_chat(
    req: ClientChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role_guard(user, ["owner", "admin", "staff"])
    business = get_client_business(db, user)

    if req.client_id is not None and req.client_id != business.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if len(message) > MAX_CLIENT_CHAT_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Message exceeds the {MAX_CLIENT_CHAT_MESSAGE_LENGTH} character limit",
        )

    reply = _execute_chat(
        business_id=business.id,
        message=message,
        db=db,
        conversation_id=None,
    )
    return {"reply": reply}


@app.get("/business/{business_id}")
def get_business(
    business_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)

    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")

    business = (
        db.query(Business)
        .filter(Business.folder_name == business_id)
        .first()
    )

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        return load_business_data(business_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Business not found")

@app.post("/create-business")
def create_business_route(
    req: CreateBusinessRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)

    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")

    owner = db.query(User).filter(User.id == req.owner_id).first()

    new_business = create_business_for_user(
        db=db,
        user=owner,
        business_name=req.business_name,
    )

    return {
        "message": "Business created successfully",
        "business_id": new_business.folder_name,
    }

# -------------------------------------------------
# PUBLIC / BUSINESS CHAT ROUTE (AI with knowledge)
# -------------------------------------------------
@app.post("/business/chat_ai")
def business_chat(
    req: PublicChatRequest,
    db: Session = Depends(get_db),
    request: Request = None,  # <-- needed for IP address
):
    business = (
        db.query(Business)
        .filter(Business.folder_name == req.business_id)
        .first()
    )
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    # Monthly usage limits (existing)
    tier = "starter"
    limits = {"starter": 500, "pro": 2000, "unlimited": 999_999}
    used = count_messages_this_month(db, business.id)
    if used >= limits[tier]:
        return {"response": "Monthly message limit reached. Please upgrade your plan."}

    data = load_business_data(req.business_id)
    kb_context = retrieve_knowledge_context(db, business.id, req.message)
    knowledge_section = kb_context or data["knowledge"]

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"""
You are Loki, the AI assistant for {data['profile']['name']}.
Tone: {data['settings']['tone']}
Greeting: {data['settings']['greeting_message']}

Business Info:
Name: {data['profile']['name']}
Industry: {data['profile']['industry']}
Email: {data['profile']['contact_email']}
Website: {data['profile']['website']}

Knowledge Base:
{knowledge_section}
"""
                },
                {"role": "user", "content": req.message},
            ],
            max_tokens=data["settings"]["max_response_length"],
            timeout=15,
        ).choices[0].message.content

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Chat service unavailable")

    now_iso = datetime.utcnow().isoformat()
    convo = Conversation(
        business_id=business.id,
        started_at=now_iso,
        last_message_at=now_iso,
        tags="",
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)

    log = MessageLog(
        business_id=business.id,
        conversation_id=convo.id,
        timestamp=now_iso,
        user_message=req.message,
        bot_response=ai_response,
    )
    db.add(log)
    db.commit()

    return {"response": ai_response, "conversation_id": convo.id}


def apply_voicebot_coupon_after_checkout(
    db: Session,
    user: User,
    coupon_code: str | None,
) -> None:
    normalized = (coupon_code or "").strip().upper()
    tier = user_tier(user)
    if not normalized or tier not in COUPON_ELIGIBLE_TIERS:
        return

    business = (
        db.query(Business)
        .filter(Business.owner_id == user.id)
        .order_by(Business.id.asc())
        .first()
    )
    if business:
        record_voicebot_coupon_used(business.id, normalized)


# -------------------------------------------------
# Auth helpers and routes
# -------------------------------------------------
def get_current_admin(
    current_user: User = Depends(get_current_user)
):
    require_platform_admin(current_user)
    return current_user

@app.post("/signup")
def signup(req: SignupRequest, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(req.email)
    client_ip = get_client_ip(request)

    trial_result = check_trial_eligibility(
        db,
        email=email,
        phone=req.business_phone,
        device_fingerprint=req.device_fingerprint,
        ip_address=client_ip,
    )

    checkout_record = consume_checkout_session_for_signup(db, req.session_id, email)

    if not trial_result.eligible:
        if checkout_record.stripe_subscription_id:
            strip_subscription_trial(checkout_record.stripe_subscription_id)
        logger.info(
            "Signup proceeding without trial for email=%s reason=%s",
            email,
            trial_result.reason,
        )

    try:
        existing = db.query(User).filter(func.lower(User.email) == email).first()
    except SQLAlchemyError:
        logger.exception("Database error while checking signup email")
        raise HTTPException(status_code=500, detail="Unable to complete signup")

    if existing and existing.business_id:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = existing
    if user:
        logger.warning("Completing interrupted signup for user_id=%s", user.id)
        user.password_hash = hash_password(req.password)
        user.role = user.role or "owner"
        user.billing_status = "active"
        user.subscription_active = 1
        apply_tier_to_user(
            user,
            getattr(checkout_record, "tier", None) or checkout_record.plan_type,
        )
    else:
        user = User(
            email=email,
            password_hash=hash_password(req.password),
            subscription_active=1,
            billing_status="active",
            role="owner",
        )
        apply_tier_to_user(
            user,
            getattr(checkout_record, "tier", None) or checkout_record.plan_type,
        )
        db.add(user)

    if checkout_record.stripe_customer_id:
        user.stripe_customer_id = checkout_record.stripe_customer_id
    user.billing_status = "active"
    user.subscription_active = 1
    if not user.registered_at:
        user.registered_at = datetime.utcnow()

    try:
        db.flush()
        new_business = create_business_for_user(
            db,
            user,
            req.business_name,
            business_phone=req.business_phone,
        )
        user.business_id = new_business.id

        referral_code = req.referral_code or checkout_record.referral_code
        client_ip = None
        if request.client:
            client_ip = request.client.host
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        referrer = apply_referral_on_signup(
            db,
            new_user=user,
            referral_code=referral_code,
            signup_ip=client_ip,
        )
        ensure_user_referral_code(db, user)

        db.commit()
        db.refresh(user)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Signup failed while creating business for email=%s", email)
        raise HTTPException(
            status_code=500,
            detail="Unable to create business for this account",
        )

    if checkout_record.coupon_code and user_tier(user) in COUPON_ELIGIBLE_TIERS:
        record_voicebot_coupon_used(new_business.id, checkout_record.coupon_code)

    if trial_result.eligible:
        try:
            record_trial_enrollment(
                db,
                email=email,
                phone=req.business_phone,
                stripe_customer_id=checkout_record.stripe_customer_id or user.stripe_customer_id,
                device_fingerprint=req.device_fingerprint,
                ip_address=client_ip,
                stripe_session_id=req.session_id,
                stripe_subscription_id=checkout_record.stripe_subscription_id,
            )
        except Exception:
            logger.exception("Failed to record trial enrollment for email=%s", email)

    try:
        initialize_payment_log(req.business_name)
    except Exception:
        logger.exception(
            "Failed to initialize payment log for business=%s user_id=%s",
            req.business_name,
            user.id,
        )

    try:
        log_event(
            user_id=user.id,
            event_type="signup",
            description="New user registered",
        )
    except Exception:
        logger.exception("Failed to write signup audit log for user_id=%s", user.id)

    frontend_base = get_frontend_public_url()
    chatbot_link = f"{frontend_base}/chat.html?b={new_business.folder_name}"
    test_dashboard_link = f"{frontend_base}/client-dashboard.html"
    embed_code = f"""<script
  src="{frontend_base}/widget.js"
  data-business="{new_business.folder_name}"
></script>"""
    referral_link = build_referral_link(user.referral_code)

    if should_send_chatbot_welcome_email(user):
        try:
            send_welcome_email_with_referral(
                to_email=user.email,
                business_name=req.business_name,
                chatbot_link=chatbot_link,
                dashboard_link=test_dashboard_link,
                embed_code=embed_code,
                referral_link=referral_link,
            )
        except Exception:
            logger.exception("Failed to send signup email for user_id=%s", user.id)

    try:
        send_product_welcome_emails_if_needed(
            db,
            user,
            client_name=req.business_name,
        )
    except Exception:
        logger.exception("Failed to send product welcome email for user_id=%s", user.id)

    if referrer:
        try:
            from referral_utils import get_referrer_display_name

            send_referred_user_welcome_email(
                to_email=user.email,
                business_name=req.business_name,
                referrer_name=get_referrer_display_name(db, referrer),
            )
        except Exception:
            logger.exception(
                "Failed to send referred-user welcome email for user_id=%s",
                user.id,
            )

    billing_status = (user.billing_status or "inactive").strip().lower()
    if billing_status == "active":
        client_ip = None
        if request.client:
            client_ip = request.client.host
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        try:
            send_admin_registration_notification(
                user_email=user.email,
                business_name=req.business_name,
                business_phone=req.business_phone,
                billing_status=user.billing_status or "active",
                stripe_customer_id=user.stripe_customer_id,
                registered_at=datetime.utcnow().isoformat() + "Z",
                client_ip=client_ip,
            )
            logger.info("Admin notified of new registration: %s", user.email)
        except Exception:
            logger.exception(
                "Failed to send admin registration notification for user_id=%s",
                user.id,
            )

    return {
        "message": "Signup successful",
        "business_id": new_business.folder_name,
        "referral_link": referral_link,
    }

@app.post("/admin/create_business_for_existing_user")
def create_business_for_existing_user(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    email = data.get("email")
    business_name = data.get("business_name")

    if not email or not business_name:
        raise HTTPException(status_code=400, detail="Email and business name required")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    business = create_business_for_user(db, user, business_name)

    try:
        initialize_payment_log(business_name)
    except Exception:
        logger.exception(
            "Failed to initialize payment log for business=%s user_id=%s",
            business_name,
            user.id,
        )

    return {"message": "Business created", "business_id": business.id}

@app.post("/invite_user")
def invite_user(
    req: InviteRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)
    require_role_guard(user, ["owner"])

    if req.role not in ["admin", "staff"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    new_user = User(
        email=req.email,
        password_hash="",
        role=req.role,
        business_id=user.business_id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User invited"}

@app.get("/team")
def team(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)

    if user.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    business = (
        db.query(Business)
        .filter(Business.id == user.business_id)
        .first()
    )

    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    users = db.query(User).filter(User.business_id == business.id).all()
    return [{"id": u.id, "email": u.email, "role": u.role} for u in users]

# -------------------------------------------------
# Export routes
# -------------------------------------------------
@app.get("/export/conversation/{convo_id}")
def export_conversation(
    convo_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    convo = (
        db.query(Conversation)
        .filter(
            Conversation.id == convo_id,
            Conversation.business_id == user.business_id,
        )
        .first()
    )

    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    logs = (
        db.query(MessageLog)
        .filter(MessageLog.conversation_id == convo_id)
        .order_by(MessageLog.timestamp.asc())
        .all()
    )

    csv_data = "timestamp,user_message,bot_response\n"
    for log in logs:
        csv_data += f"{log.timestamp},{log.user_message},{log.bot_response}\n"

    return csv_data

@app.get("/export/business/{business_id}")
def export_business(
    business_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")

    business = (
        db.query(Business)
        .filter(Business.folder_name == business_id)
        .first()
    )

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    business_path = os.path.join("businesses", business_id)

    if not os.path.exists(business_path):
        raise HTTPException(status_code=404, detail="Business folder not found")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(business_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, business_path)
                zipf.write(full_path, arcname)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={business_id}.zip"
        },
    )

@app.get("/export/all")
def export_all(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    business_id = user.business_id
    logs = (
        db.query(MessageLog)
        .filter(MessageLog.business_id == business_id)
        .order_by(MessageLog.timestamp.asc())
        .all()
    )

    csv_data = "conversation_id,timestamp,user_message,bot_response\n"
    for log in logs:
        csv_data += (
            f"{log.conversation_id},{log.timestamp},"
            f"{log.user_message},{log.bot_response}\n"
        )

    return csv_data

@app.post("/export/filtered")
def export_filtered(
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    business_id = user.business_id
    convo_ids = payload["conversation_ids"]

    logs = (
        db.query(MessageLog)
        .filter(
            MessageLog.business_id == business_id,
            MessageLog.conversation_id.in_(convo_ids),
        )
        .order_by(MessageLog.timestamp.asc())
        .all()
    )

    csv_data = "conversation_id,timestamp,user_message,bot_response\n"
    for log in logs:
        csv_data += (
            f"{log.conversation_id},{log.timestamp},"
            f"{log.user_message},{log.bot_response}\n"
        )

    return csv_data

# -------------------------------------------------
# Stripe Checkout
# -------------------------------------------------
@app.post("/create-checkout-session")
def create_checkout_session_post(
    request: Request,
    req: CreateCheckoutSessionRequest | None = None,
    db: Session = Depends(get_db),
):
    referral_code = req.referral_code if req else None
    device_fingerprint = req.device_fingerprint if req else None
    plan_type = (req.tier or req.plan_type) if req else "chatbot"
    coupon_code = req.coupon_code if req else None
    return create_billing_first_checkout_session(
        db,
        referral_code=referral_code,
        device_fingerprint=device_fingerprint,
        ip_address=get_client_ip(request),
        plan_type=plan_type,
        coupon_code=coupon_code,
    )


@app.get("/create-checkout-session")
def create_checkout_session(
    request: Request,
    email: str | None = None,
    business_id: str | None = None,
    device_fingerprint: str | None = None,
    db: Session = Depends(get_db),
):
    user = resolve_checkout_user(db, email=email, business_id=business_id)
    checkout_url = create_subscription_checkout_session(
        db,
        user,
        device_fingerprint=device_fingerprint,
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=checkout_url, status_code=303)


@app.get("/verify-checkout-session")
def verify_checkout_session(session_id: str, db: Session = Depends(get_db)):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return verify_checkout_session_for_registration(db, session_id)


# -------------------------------------------------
# Stripe Webhook
# -------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: Session = Depends(get_db),
):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        checkout_record = upsert_billing_checkout_session(db, data)
        try:
            process_checkout_trial_protection(db, data)
        except Exception:
            logger.exception("Trial protection failed for checkout session=%s", data.get("id"))
        email = (
            (data.get("customer_details") or {}).get("email")
            or data.get("customer_email")
        )
        if email:
            user = db.query(User).filter(
                func.lower(User.email) == normalize_email(email)
            ).first()
            if user:
                user.subscription_active = 1
                user.billing_status = "active"
                metadata = data.get("metadata") or {}
                tier_value = metadata.get("tier") or metadata.get("plan_type")
                price_id = None
                if not tier_value and data.get("subscription"):
                    try:
                        subscription = stripe.Subscription.retrieve(data.get("subscription"))
                        items = (subscription.get("items") or {}).get("data") or []
                        if items:
                            price_id = items[0].get("price", {}).get("id")
                            tier_value = tier_from_stripe_price(price_id)
                    except stripe.error.StripeError:
                        logger.warning("Unable to resolve tier from checkout webhook")
                if tier_value:
                    apply_tier_to_user(user, tier_value)
                elif getattr(checkout_record, "tier", None):
                    apply_tier_to_user(user, checkout_record.tier)
                if data.get("customer"):
                    user.stripe_customer_id = data.get("customer")
                db.commit()
                db.refresh(user)
                coupon_code = metadata.get("coupon_code") or checkout_record.coupon_code
                apply_voicebot_coupon_after_checkout(db, user, coupon_code)
                try:
                    send_product_welcome_emails_if_needed(db, user)
                except Exception:
                    logger.exception(
                        "Failed to send product welcome email for user_id=%s",
                        user.id,
                    )
                log_event(
                    user_id=user.id,
                    event_type="subscription_activated",
                    description="Stripe checkout completed",
                )

    elif event_type == "customer.subscription.created":
        customer_id = data.get("customer")
        if customer_id:
            user = (
                db.query(User)
                .filter(User.stripe_customer_id == customer_id)
                .first()
            )
            if user:
                user.subscription_active = 1
                user.billing_status = "active"
                db.commit()

    elif event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        amount_paid = int(data.get("amount_paid") or 0)
        if customer_id and amount_paid > 0:
            user = (
                db.query(User)
                .filter(User.stripe_customer_id == customer_id)
                .first()
            )
            if user:
                conversion = process_referral_conversion(
                    db,
                    user,
                    invoice_id=data.get("id"),
                )
                business = (
                    db.query(Business)
                    .filter(Business.owner_id == user.id)
                    .order_by(Business.id.asc())
                    .first()
                )
                if business:
                    try:
                        await append_payment_log_async(
                            business.name,
                            amount_cents=amount_paid,
                            invoice_id=data.get("id") or "",
                            description=payment_description_from_invoice(data),
                            currency=(data.get("currency") or "usd"),
                        )
                    except Exception:
                        logger.exception(
                            "Failed to append payment log user_id=%s invoice_id=%s",
                            user.id,
                            data.get("id"),
                        )
                if conversion:
                    referrer = conversion["referrer"]
                    referred_user = conversion["referred_user"]
                    updated_renewal = conversion.get("updated_renewal")
                    renewal_text = (
                        updated_renewal.strftime("%B %d, %Y")
                        if updated_renewal
                        else None
                    )
                    referral_link = build_referral_link(referrer.referral_code or "")

                    try:
                        send_referral_reward_email(
                            to_email=referrer.email,
                            referral_link=referral_link,
                            updated_renewal_date=renewal_text,
                            successful_referrals=int(referrer.referral_count or 0),
                            free_months_earned=int(referrer.free_months_earned or 0),
                        )
                    except Exception:
                        logger.exception(
                            "Failed to send referral reward email referrer_id=%s",
                            referrer.id,
                        )

                    try:
                        send_admin_referral_conversion_email(
                            referrer_name=conversion["referrer_name"],
                            referrer_email=referrer.email,
                            referred_name=conversion["referred_name"],
                            referred_email=referred_user.email,
                            converted_at=datetime.utcnow().isoformat() + "Z",
                        )
                    except Exception:
                        logger.exception("Failed to send admin referral conversion email")

                    log_event(
                        user_id=referrer.id,
                        event_type="referral_reward_granted",
                        description=(
                            f"Referral conversion rewarded for referred_user_id={referred_user.id}"
                        ),
                    )

    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        user = (
            db.query(User)
            .filter(User.stripe_customer_id == customer_id)
            .first()
        )
        if user:
            log_event(
                user_id=user.id,
                event_type="payment_failed",
                description="Stripe reported a failed payment",
            )
            send_email(
                to_email=user.email,
                subject="Payment Failed",
                body="Your recent payment failed. Please update your billing information.",
            )

    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user = (
            db.query(User)
            .filter(User.stripe_customer_id == customer_id)
            .first()
        )
        if user:
            log_event(
                user_id=user.id,
                event_type="subscription_canceled",
                description="Stripe reported subscription cancellation",
            )
            user.subscription_active = 0
            user.billing_status = "inactive"
            db.commit()
            send_email(
                to_email=user.email,
                subject="Subscription Canceled",
                body=(
                    "Your subscription has been canceled. "
                    "Your chatbot is now inactive."
                ),
            )

    return {"status": "success"}


from twilio_routes import router as twilio_router

app.include_router(twilio_router)


# Keep CORS as the outermost ASGI layer so even unexpected 500 responses include
# CORS headers and browsers show the real JSON error instead of masking it.
app = CORSMiddleware(
    app=app,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)
