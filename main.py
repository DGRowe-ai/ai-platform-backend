from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Request,
    Header,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
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
from database import Base, engine, SessionLocal
from models import User, Business, MessageLog, Conversation
Base.metadata.create_all(bind=engine)

# -------------------------------------------------
# Auth utilities
# -------------------------------------------------
from auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_role,
)

# -------------------------------------------------
# Business creation engine
# -------------------------------------------------
from business_utils import create_business_for_user

# -------------------------------------------------
# Audit + email + analytics utilities
# -------------------------------------------------
from audit_utils import log_event
from email_utils import send_email
from admin_analytics import get_admin_analytics
from business_settings_utils import get_settings

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
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------------------------------
# Chat history utilities
# -------------------------------------------------
from chat_history_utils import save_message, get_history

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

    user_id = user.id
    role = user.role
    subscription_active = user.subscription_active
    business_id = user.business_id
    businesses = get_business_summaries_for_user(db, user_id, fail_on_error=False)

    token = create_access_token({
        "user_id": user_id,
        "role": role,
        "subscription_active": subscription_active,
        "business_id": business_id
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "subscription_active": subscription_active,
        "role": role,
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
def _execute_chat(
    business_id: str,
    message: str,
    db: Session,
    conversation_id: int | None = None,
):
    settings = get_settings(business_id)

    system_prompt = f"""
    You are a chatbot for this business.
    Tone: {settings.chatbot_tone}
    Greeting: {settings.greeting_message}
    Custom instructions: {settings.custom_instructions}
    """

    save_message(business_id, conversation_id, "user", message)
    history = get_history(business_id)

    conversation = [{"role": "system", "content": system_prompt}]
    for msg in history:
        conversation.append({"role": msg.role, "content": msg.message})
    conversation.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation,
        timeout=15,
    )

    bot_reply = response.choices[0].message.content
    save_message(business_id, conversation_id, "assistant", bot_reply)

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

@app.get("/my_businesses")
def my_businesses(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)

    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")

    return get_business_summaries_for_user(db, user.id)

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
{data['knowledge']}
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
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return current_user

@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        subscription_active=0,
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_event(
        user_id=user.id,
        event_type="signup",
        description="New user registered",
    )

    new_business = create_business_for_user(db, user, req.business_name)
    user.business_id = new_business.id
    db.commit()

    frontend_base = "https://ai-platform-frontend-uaaa.onrender.com"
    chatbot_link = f"{frontend_base}/chat.html?b={user.business_id}"
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
    Need Help?
    ----------------------------------------
    If you need help installing the chatbot or customizing responses,
    just reply to this email and we'll take care of you.

    Thanks for choosing Rowe AI!
    """

    send_email(
        to_email=user.email,
        subject=f"Your Rowe AI Chatbot Is Ready, {req.business_name}!",
        body=email_body,
    )

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
