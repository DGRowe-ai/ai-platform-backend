from fastapi import FastAPI, HTTPException, Depends, Request, Header
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from openai import OpenAI
import json
import os
import stripe

# Load environment
load_dotenv()

# Database + models
from database import Base, engine, SessionLocal
from models import User, Business, MessageLog, Conversation

# Auth utilities
from auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)


# Business creation engine
from business_utils import create_business_for_user

# Audit + email + admin routes
from audit_utils import log_event
from email_utils import send_email
from admin_analytics import get_admin_analytics
from business_settings_routes import router as business_settings_router

# ⭐ Step 26 — Business settings utilities
from business_settings_utils import get_settings

# Stripe setup
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# OpenAI setup
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# FastAPI app
app = FastAPI()
Base.metadata.create_all(bind=engine)
app.include_router(business_settings_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from fastapi import Response, Depends
from pydantic import BaseModel
from datetime import datetime
from chat_history_utils import save_message, get_history
from auth_utils import get_current_user, require_role
from database import SessionLocal
from openai_client import client  # your existing OpenAI client import

# -------------------------------
# CHAT REQUEST MODEL
# -------------------------------
class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None

@app.get("/")
def health_check():
    return {"status": "ok"}

@app.head("/")
def health_check_head():
    return Response(status_code=200)

# -------------------------------
# CHAT ROUTE (Step 27 updated)
# -------------------------------
@app.post("/chat")
def chat(request: ChatRequest, user=Depends(get_current_user)):
    db = SessionLocal()

    # Load business-level chatbot settings
    settings = get_settings(user.business_id)

    # Build system prompt using business settings
    system_prompt = f"""
    You are a chatbot for this business.
    Tone: {settings.chatbot_tone}
    Greeting: {settings.greeting_message}
    Custom instructions: {settings.custom_instructions}
    """

    # Save user message
    save_message(user.business_id, user.id, "user", request.message)

    # Load message history for context
    history = get_history(user.business_id)

    # Build conversation context for AI
    conversation = [{"role": "system", "content": system_prompt}]
    for msg in history:
        conversation.append({"role": msg.role, "content": msg.message})
    conversation.append({"role": "user", "content": request.message})

       # Call OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation
    )

    bot_reply = response.choices[0].message.content

    # Save assistant reply
    save_message(user.business_id, user.id, "assistant", bot_reply)


    # Log conversation (existing MessageLog)
    log = MessageLog(
        business_id=user.business_id,
        conversation_id=request.conversation_id,
        user_message=request.message,
        bot_response=bot_reply,
        timestamp=datetime.utcnow().isoformat(),
    )
    db.add(log)
    db.commit()
    db.close()

    return {"response": bot_reply}

# -------------------------------
# BUSINESS CHAT HISTORY ROUTE
# -------------------------------
@app.get("/business/history")
def get_business_history(user=Depends(get_current_user)):
    """
    Fetch the last 200 chatbot messages for the current business.
    Accessible only to business owners.
    """
    history = get_history(user.business_id, limit=200)
    return history










# Load business data
def load_business_data(business_id: str):
    base = Path(__file__).parent / "businesses" / business_id
    profile = json.loads((base / "profile.json").read_text())
    settings = json.loads((base / "settings.json").read_text())
    knowledge = (base / "knowledge.txt").read_text()
    return {"profile": profile, "settings": settings, "knowledge": knowledge}


# Request models
class CreateBusinessRequest(BaseModel):
    owner_id: int
    business_name: str


class ChatRequest(BaseModel):
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


# Guards
def require_subscription(user: User = Depends(get_current_user)):
    if not user.subscription_active:
        raise HTTPException(status_code=402, detail="Subscription required")
    return user


def require_role(user: User, allowed_roles: list[str]):
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Not authorized")


# Analytics helper
def count_messages_this_month(db: Session, business_id: int) -> int:
    now = datetime.utcnow()
    month = now.strftime("%Y-%m")
    return (
        db.query(MessageLog)
        .filter(
            MessageLog.business_id == business_id,
            MessageLog.timestamp.startswith(month),
        )
        .count()
    )


# Routes
@app.get("/ping")
def ping():
    return {"message": "pong"}


@app.get("/my_businesses")
def my_businesses(user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    businesses = db.query(Business).filter(Business.owner_id == user.id).all()
    return [
        {"id": b.id, "name": b.name, "folder_name": b.folder_name}
        for b in businesses
    ]


@app.get("/business/{business_id}")
def get_business(
    business_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)
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


@app.post("/chat")
def chat(
    req: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)
    business = (
        db.query(Business)
        .filter(Business.folder_name == req.business_id)
        .first()
    )
    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Usage limits
    tier = "starter"
    limits = {"starter": 500, "pro": 2000, "unlimited": 999_999}
    used = count_messages_this_month(db, business.id)
    if used >= limits[tier]:
        return {
            "response": "Monthly message limit reached. Please upgrade your plan."
        }

    # Generate AI response
    data = load_business_data(req.business_id)
    ai_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": req.message},
        ],
        max_tokens=data["settings"]["max_response_length"],
    ).choices[0].message.content

    # Log message + conversation
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

    log_event(
        user_id=user.id,
        event_type="chat_message",
        description="User sent a chatbot message",
    )
    return {"response": ai_response, "conversation_id": convo.id}


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

    send_email(
        to_email=user.email,
        subject="Welcome to Your AI Chatbot Platform!",
        body="Thanks for signing up. Your chatbot is now ready to use.",
    )
    return {"message": "Signup successful"}


@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.password_hash:
        return {"first_time": True}

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": user.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "subscription_active": user.subscription_active,
        "role": user.role,
    }


@app.post("/invite_user")
def invite_user(
    req: InviteRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)
    require_role(user, ["owner"])
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
def team(user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    business = (
        db.query(Business)
        .filter(Business.id == user.business_id)
        .first()
    )
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    users = db.query(User).filter(User.business_id == business.id).all()
    return [
        {"id": u.id, "email": u.email, "role": u.role}
        for u in users
    ]


# Export routes
@app.get("/export/conversation/{convo_id}")
def export_conversation(
    convo_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convo = db.query(Conversation).filter(
        Conversation.id == convo_id,
        Conversation.business_id == user.business_id,
    ).first()
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


@app.get("/export/all")
def export_all(user=Depends(get_current_user), db: Session = Depends(get_db)):
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


# Stripe Webhook
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    data = event["data"]["object"]

    # 1. Handle checkout completion
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

    # 2. Handle payment failure
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

    # 3. Handle subscription canceled
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
                body="Your subscription has been canceled. Your chatbot is now inactive.",
            )

    return {"status": "success"}
