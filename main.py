from fastapi import FastAPI, HTTPException, Depends, Request, Header
from pydantic import BaseModel
from pathlib import Path
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware

# Database + models
from database import Base, engine, SessionLocal
from sqlalchemy.orm import Session
from models import User, Business

# Auth utilities
from auth_utils import hash_password, verify_password, create_access_token, get_current_user

# Business creation engine (Step 12)
from business_utils import create_business_for_user

# -----------------------------
# 🔥 Stripe Setup
# -----------------------------
import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# -----------------------------
# OpenAI Setup
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# FastAPI app
app = FastAPI()

# Create database tables
Base.metadata.create_all(bind=engine)

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Database session dependency
# -----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# Load business data
# -----------------------------
def load_business_data(business_id: str):
    base = Path(__file__).parent / "businesses" / business_id

    profile = json.loads((base / "profile.json").read_text())
    settings = json.loads((base / "settings.json").read_text())
    knowledge = (base / "knowledge.txt").read_text()

    return {
        "profile": profile,
        "settings": settings,
        "knowledge": knowledge
    }

# -----------------------------
# Request models
# -----------------------------
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

# -----------------------------
# AI Response Generator
# -----------------------------
def generate_ai_response(business_data, user_message):
    prompt = f"""
You are a customer support chatbot for the business:
{business_data['profile']['name']}.
Industry: {business_data['profile']['industry']}

Business knowledge:
{business_data['knowledge']}

Chatbot tone: {business_data['settings']['tone']}

User message:
{user_message}

Respond clearly and accurately using the business information above.
Always reply in the same language the user is using.
If the user switches languages, follow their lead.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=business_data["settings"]["max_response_length"]
    )

    return response.choices[0].message.content

# -----------------------------
# Subscription Guard
# -----------------------------
def require_subscription(user: User):
    if user.subscription_active != 1:
        raise HTTPException(status_code=402, detail="Subscription required")

# -----------------------------
# Routes
# -----------------------------
@app.get("/ping")
def ping():
    return {"message": "pong"}

# Step 11A - Get logged-in user's businesses
@app.get("/my_businesses")
def my_businesses(user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    businesses = db.query(Business).filter(Business.owner_id == user.id).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "folder_name": b.folder_name
        }
        for b in businesses
    ]

# Step 11B - Protected business loader
@app.get("/business/{business_id}")
def get_business(business_id: str, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
from fastapi import FastAPI, HTTPException, Depends, Request, Header
from pydantic import BaseModel
from pathlib import Path
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

# Database + models
from database import Base, engine, SessionLocal
from sqlalchemy.orm import Session
from models import User, Business, MessageLog

# Auth utilities
from auth_utils import hash_password, verify_password, create_access_token, get_current_user

# Business creation engine (Step 12)
from business_utils import create_business_for_user

# -----------------------------
# 🔥 Stripe Setup
# -----------------------------
import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# -----------------------------
# OpenAI Setup
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# FastAPI app
app = FastAPI()

# Create database tables
Base.metadata.create_all(bind=engine)

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Database session dependency
# -----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# Load business data
# -----------------------------
def load_business_data(business_id: str):
    base = Path(__file__).parent / "businesses" / business_id

    profile = json.loads((base / "profile.json").read_text())
    settings = json.loads((base / "settings.json").read_text())
    knowledge = (base / "knowledge.txt").read_text()

    return {
        "profile": profile,
        "settings": settings,
        "knowledge": knowledge
    }

# -----------------------------
# Request models
# -----------------------------
class CreateBusinessRequest(BaseModel):
    owner_id: int
    business_name: str

class ChatRequest(BaseModel):
    business_id: str
    message: str

class SignupRequest(BaseModel):
    email: str
    password: str
from fastapi import FastAPI, HTTPException, Depends, Request, Header
from pydantic import BaseModel
from pathlib import Path
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

# Database + models
from database import Base, engine, SessionLocal
from sqlalchemy.orm import Session
from models import User, Business, MessageLog

# Auth utilities
from auth_utils import hash_password, verify_password, create_access_token, get_current_user

# Business creation engine (Step 12)
from business_utils import create_business_for_user

# -----------------------------
# 🔥 Stripe Setup
# -----------------------------
import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# -----------------------------
# OpenAI Setup
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# FastAPI app
app = FastAPI()

# Create database tables
Base.metadata.create_all(bind=engine)

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Database session dependency
# -----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# Load business data
# -----------------------------
def load_business_data(business_id: str):
    base = Path(__file__).parent / "businesses" / business_id

    profile = json.loads((base / "profile.json").read_text())
    settings = json.loads((base / "settings.json").read_text())
    knowledge = (base / "knowledge.txt").read_text()

    return {
        "profile": profile,
        "settings": settings,
        "knowledge": knowledge
    }

# -----------------------------
# Request models
# -----------------------------
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
    role: str  # admin or staff

class SetPasswordRequest(BaseModel):
    user_id: int
    password: str

# -----------------------------
# AI Response Generator
# -----------------------------
def generate_ai_response(business_data, user_message):
    prompt = f"""
You are a customer support chatbot for the business:
{business_data['profile']['name']}.
Industry: {business_data['profile']['industry']}

Business knowledge:
{business_data['knowledge']}

Chatbot tone: {business_data['settings']['tone']}

User message:
{user_message}

Respond clearly and accurately using the business information above.
Always reply in the same language the user is using.
If the user switches languages, follow their lead.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=business_data["settings"]["max_response_length"]
    )

    return response.choices[0].message.content

# -----------------------------
# Subscription Guard
# -----------------------------
def require_subscription(user: User):
    if user.subscription_active != 1:
        raise HTTPException(status_code=402, detail="Subscription required")

# -----------------------------
# Role Guard (Step 17)
# -----------------------------
def require_role(user: User, allowed_roles):
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Not authorized")

# -----------------------------
# Analytics Helpers
# -----------------------------
def count_messages_this_month(db, business_id):
    now = datetime.utcnow()
    month = now.strftime("%Y-%m")
    return db.query(MessageLog).filter(
        MessageLog.business_id == business_id,
        MessageLog.timestamp.startswith(month)
    ).count()

# -----------------------------
# Routes
# -----------------------------
@app.get("/ping")
def ping():
    return {"message": "pong"}

# Step 11A - Get logged-in user's businesses
@app.get("/my_businesses")
def my_businesses(user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    businesses = db.query(Business).filter(Business.owner_id == user.id).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "folder_name": b.folder_name
        }
        for b in businesses
    ]

# Step 11B - Protected business loader
@app.get("/business/{business_id}")
def get_business(business_id: str, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)

    business = db.query(Business).filter(Business.folder_name == business_id).first()

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        return load_business_data(business_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Business not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-business")
def create_business_route(req: CreateBusinessRequest, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)

    new_business = create_business_for_user(
        db=db,
        user=db.query(User).filter(User.id == req.owner_id).first(),
        business_name=req.business_name
    )
    return {
        "message": "Business created successfully",
        "business_id": new_business.folder_name
    }

# -----------------------------
# Step 16 — Chat with Logging + Limits
# -----------------------------
@app.post("/chat")
def chat(req: ChatRequest, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)

    business = db.query(Business).filter(Business.folder_name == req.business_id).first()
    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Usage limits (starter tier for now)
    tier = "starter"
    limits = {
        "starter": 500,
        "pro": 2000,
        "unlimited": 999999
    }

    used = count_messages_this_month(db, business.id)
    if used >= limits[tier]:
        return {"response": "Monthly message limit reached. Please upgrade your plan."}

    # Generate AI response
    data = load_business_data(req.business_id)
    ai_response = generate_ai_response(data, req.message)

    # Log message
    log = MessageLog(
        business_id=business.id,
        timestamp=datetime.utcnow().isoformat(),
        user_message=req.message,
        bot_response=ai_response
    )
    db.add(log)
    db.commit()

    return {"response": ai_response}

# -----------------------------
# Step 12 — Signup creates business automatically (Step 17 updated)
# -----------------------------
@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        subscription_active=0,
        role="owner"  # Step 17: owner
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    new_business = create_business_for_user(db, user, req.business_name)

    # Step 17: link user to business
    user.business_id = new_business.id
    db.commit()

    return {"message": "Signup successful"}

# -----------------------------
# Login (Step 17 updated)
# -----------------------------
@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Invited user with no password yet
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
        "role": user.role
    }

# -----------------------------
# Set password (for invited users)
# -----------------------------
@app.post("/set_password")
def set_password(req: SetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(req.password)
    db.commit()

    return {"message": "Password set successfully"}

# -----------------------------
# Invite user (Step 17)
# -----------------------------
@app.post("/invite_user")
def invite_user(req: InviteRequest, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    require_role(user, ["owner"])

    if req.role not in ["admin", "staff"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    new_user = User(
        email=req.email,
        password_hash="",  # no password yet
        role=req.role,
        business_id=user.business_id
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User invited"}

# -----------------------------
# Team list (Step 17)
# -----------------------------
@app.get("/team")
def team(user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)

    business = db.query(Business).filter(Business.id == user.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    users = db.query(User).filter(User.business_id == business.id).all()

    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role
        }
        for u in users
    ]

# -----------------------------
# Step 11C - Protected Update Business (role protected)
# -----------------------------
@app.post("/update_business")
def update_business(payload: dict, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    require_role(user, ["owner", "admin"])

    business_id = payload["business_id"]

    business = db.query(Business).filter(Business.folder_name == business_id).first()

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    base = Path(__file__).parent / "businesses" / business_id

    (base / "profile.json").write_text(json.dumps(payload["profile"], indent=4))
    (base / "settings.json").write_text(json.dumps(payload["settings"], indent=4))
    (base / "knowledge.txt").write_text(payload["knowledge"])

    return {"message": "Business updated"}

# -----------------------------
# Step 16 — Analytics Route (role protected)
# -----------------------------
@app.get("/analytics/{business_id}")
def analytics(business_id: str, user = Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)
    require_role(user, ["owner", "admin", "staff"])

    business = db.query(Business).filter(Business.folder_name == business_id).first()

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    logs = db.query(MessageLog).filter(MessageLog.business_id == business.id).all()

    return {
        "total_messages": len(logs),
        "messages_this_month": count_messages_this_month(db, business.id),
        "history": [
            {
                "timestamp": log.timestamp,
                "user_message": log.user_message,
                "bot_response": log.bot_response
            }
            for log in logs
        ]
    }

# -----------------------------
# Stripe Subscription Checkout (owner only)
# -----------------------------
@app.post("/create-checkout-session")
def create_checkout_session(user = Depends(get_current_user)):
    require_subscription(user)
    require_role(user, ["owner"])
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price_data": {
                        "currency": "cad",
                        "product": "prod_UXhofxvvPGlEfX",
                        "unit_amount": 2500,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ],
            customer_email=user.email,
            success_url="https://ai-platform-backend-ny15.onrender.com/success",
            cancel_url="https://ai-platform-backend-ny15.onrender.com/cancel",
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/success")
def checkout_success():
    return {"message": "Payment successful. Subscription activated."}

@app.get("/cancel")
def checkout_cancel():
    return {"message": "Payment canceled. No changes made."}

# -----------------------------
# Stripe Webhook
# -----------------------------
WEBHOOK_SECRET = "whsec_3QLASsmGV6iBHQqTeY6pQvPk013PNF58"

@app.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None), db: Session = Depends(get_db)):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Handle checkout completion
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")

        user = db.query(User).filter(User.email == email).first()
        if user:
            user.subscription_active = 1
            db.commit()
            print("Subscription activated for:", email)

    return {"status": "success"}
