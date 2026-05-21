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
# Step 12 — Signup creates business automatically
# -----------------------------
@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        subscription_active=0
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    create_business_for_user(db, user, req.business_name)

    return {"message": "Signup successful"}

@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status