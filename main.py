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
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from openai import OpenAI
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
DEPLOYMENT_VERSION = "stripe-checkout-onboarding-2026-06-11-1"

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
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]


def get_cors_origins():
    configured_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]
    return origins or DEFAULT_CORS_ORIGINS

# -------------------------------------------------
# Database + models
# -------------------------------------------------
from database import Base, engine, SessionLocal, get_db
from models import User, Business, MessageLog, Conversation, Payment, ReportRun, KnowledgeFile, KnowledgeEmbedding
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
from email_utils import send_email
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
    create_subscription_checkout_session,
    resolve_checkout_user,
)

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


ensure_business_settings_schema()
ensure_user_stripe_schema()
apply_admin_email_allowlist()

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

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "subscription_active": subscription_active,
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
        subscription_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User created", "user_id": new_user.id}

# -------------------------------------------------
# Routers
# -------------------------------------------------
from admin_routes import router as admin_router
from business_settings_routes import router as business_settings_router
app.include_router(admin_router)
app.include_router(business_settings_router)

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


def _execute_chat(
    business_id: str,
    message: str,
    db: Session,
    conversation_id: int | None = None,
):
    business = resolve_business(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

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

    system_prompt = f"""
    You are a chatbot for this business.
    Tone: {settings.get('tone', 'friendly')}
    Welcome message: {settings.get('welcome_message', 'Hello! How can I help you today?')}
    Custom instructions: {settings.get('custom_instructions', '')}
    Frequently asked questions:
    {faq_text or 'No FAQs configured.'}
    """

    if kb_context:
        system_prompt += f"\nRelevant uploaded knowledge:\n{kb_context}"
    if legacy_kb:
        system_prompt += f"\nAdditional business knowledge:\n{legacy_kb[:4000]}"

    save_message(business.id, conversation_id, "user", message)
    history = get_history(business.id)

    conversation = [{"role": "system", "content": system_prompt}]
    for msg in history:
        conversation.append({"role": msg.role, "content": msg.message})
    conversation.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation,
        max_tokens=settings.get("max_response_length", 300),
        timeout=15,
    )

    bot_reply = response.choices[0].message.content
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
        raise HTTPException(status_code=404, detail="Business not found for this account")

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


# -------------------------------------------------
# Auth helpers and routes
# -------------------------------------------------
def get_current_admin(
    current_user: User = Depends(get_current_user)
):
    require_platform_admin(current_user)
    return current_user

@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = normalize_email(req.email)
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
        if user.subscription_active is None:
            user.subscription_active = 0
    else:
        user = User(
            email=email,
            password_hash=hash_password(req.password),
            subscription_active=0,
            role="owner",
        )
        db.add(user)

    try:
        db.flush()
        new_business = create_business_for_user(db, user, req.business_name)
        user.business_id = new_business.id
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

    try:
        log_event(
            user_id=user.id,
            event_type="signup",
            description="New user registered",
        )
    except Exception:
        logger.exception("Failed to write signup audit log for user_id=%s", user.id)

    frontend_base = "https://ai-platform-frontend-uaaa.onrender.com"
    chatbot_link = f"{frontend_base}/chat.html?b={user.business_id}"
    checkout_link = build_checkout_activation_url(user.email)
    embed_code = f"""
    <!-- Rowe AI Chatbot -->
    <script src="{frontend_base}/widget-frame.js?b={user.business_id}"></script>
    """

    email_body = f"""
    Welcome to Rowe AI, {req.business_name}!

    Your AI chatbot is now live and ready to use.

    ----------------------------------------
    Your Chatbot Link (for testing)
    ----------------------------------------
    {chatbot_link}

    ----------------------------------------
    Your Website Embed Code
    ----------------------------------------
    Paste this code anywhere on your website's HTML to activate your chatbot:

    {embed_code}

    ----------------------------------------
    Activate Your Subscription
    ----------------------------------------
    To activate your subscription, complete your billing setup here:
    {checkout_link}

    ----------------------------------------
    Need Help?
    ----------------------------------------
    If you need help installing the chatbot or customizing responses,
    just reply to this email and we'll take care of you.

    Thanks for choosing Rowe AI!
    """

    try:
        send_email(
            to_email=user.email,
            subject=f"Your Rowe AI Chatbot Is Ready, {req.business_name}!",
            body=email_body,
        )
    except Exception:
        logger.exception("Failed to send signup email for user_id=%s", user.id)

    return {
        "message": "Signup successful",
        "business_id": new_business.folder_name,
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
@app.get("/create-checkout-session")
def create_checkout_session(
    email: str | None = None,
    business_id: str | None = None,
    db: Session = Depends(get_db),
):
    user = resolve_checkout_user(db, email=email, business_id=business_id)
    checkout_url = create_subscription_checkout_session(db, user)
    return RedirectResponse(url=checkout_url, status_code=303)


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
        email = data.get("customer_email")
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.subscription_active = 1
            db.commit()
            log_event(
                user_id=user.id,
                event_type="subscription_activated",
                description="Stripe checkout completed",
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
            send_email(
                to_email=user.email,
                subject="Subscription Canceled",
                body=(
                    "Your subscription has been canceled. "
                    "Your chatbot is now inactive."
                ),
            )

    return {"status": "success"}


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
