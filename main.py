from fastapi import FastAPI, HTTPException, Depends, Request, Header
from pydantic import BaseModel
from pathlib import Path
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()
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
from fastapi import Depends, HTTPException
from auth_utils import get_current_user
from models import User

def require_subscription(user: User = Depends(get_current_user)):
    if not user.subscription_active:
        raise HTTPException(status_code=402, detail="Subscription required")
    return user


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
@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    # Check if email already exists
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create the new user
    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        subscription_active=0,
        role="owner"  # Step 17: owner
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Send welcome email
    from .email_utils import send_email
    send_email(
        to_email=user.email,
        subject="Welcome to Your AI Chatbot Platform!",
        body="Thanks for signing up. Your chatbot is now ready to use."
    )

    return {"message": "Signup successful"}

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

# -----------------------------
# Database + models
# -----------------------------
from database import Base, engine, SessionLocal
from models import User, Business, MessageLog, Conversation

# -----------------------------
# Auth utilities
# -----------------------------
from auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)

# -----------------------------
# Business creation engine (Step 12)
# -----------------------------
from business_utils import create_business_for_user

# -----------------------------
# 🔥 Stripe Setup
# -----------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
_SECRET = "whsec_3QLASsmGV6iBHQqTeY6pQvPk013PNF58"  # keep as-is for now

# -----------------------------
# OpenAI SetupWEBHOOK
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# FastAPI app
# -----------------------------
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
        "knowledge": knowledge,
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


class TagUpdate(BaseModel):
    tags: list[str]


# -----------------------------
# AI Response Generator
# -----------------------------
def generate_ai_response(business_data, user_message: str) -> str:
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
            {"role": "user", "content": prompt},
        ],
        max_tokens=business_data["settings"]["max_response_length"],
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
def require_role(user: User, allowed_roles: list[str]):
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Not authorized")

# -----------------------------
# Analytics Helpers
# -----------------------------
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

# -----------------------------
# Routes
# -----------------------------
@app.get("/ping")
def ping():
    return {"message": "pong"}

# -----------------------------
# Step 11A - Get logged-in user's businesses
# -----------------------------
@app.get("/my_businesses")
def my_businesses(
    user=Depends(get_current_user), db: Session = Depends(get_db)
):
    require_subscription(user)
    businesses = db.query(Business).filter(Business.owner_id == user.id).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "folder_name": b.folder_name,
        }
        for b in businesses
    ]

# -----------------------------
# Step 11B - Protected business loader
# -----------------------------
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------
# Create Business
# -----------------------------
@app.post("/create-business")
def create_business_route(
    req: CreateBusinessRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)

    new_business = create_business_for_user(
        db=db,
        user=db.query(User).filter(User.id == req.owner_id).first(),
        business_name=req.business_name,
    )
    return {
        "message": "Business created successfully",
        "business_id": new_business.folder_name,
    }

# -----------------------------
# Step 16 + 18 — Chat with Logging + Conversation Sessions
# -----------------------------
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

    # Usage limits (starter tier for now)
    tier = "starter"
    limits = {
        "starter": 500,
        "pro": 2000,
        "unlimited": 999999,
    }

    used = count_messages_this_month(db, business.id)
    if used >= limits[tier]:
        return {
            "response": "Monthly message limit reached. Please upgrade your plan."
        }

    # Generate AI response
    data = load_business_data(req.business_id)
    ai_response = generate_ai_response(data, req.message)

    # Create a new conversation for now (simple model)
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

    # Log message
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
        role="owner",
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
        "role": user.role,
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

# -----------------------------
# Team list (Step 17)
# -----------------------------
@app.get("/team")
def team(user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_subscription(user)

    business = (
        db.query(Business).filter(Business.id == user.business_id).first()
    )
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    users = db.query(User).filter(User.business_id == business.id).all()

    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
        }
        for u in users
    ]

# -----------------------------
# Step 11C - Protected Update Business (role protected)
# -----------------------------
@app.post("/update_business")
def update_business(
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)
    require_role(user, ["owner", "admin"])

    business_id = payload["business_id"]

    business = (
        db.query(Business)
        .filter(Business.folder_name == business_id)
        .first()
    )

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    base = Path(__file__).parent / "businesses" / business_id

    (base / "profile.json").write_text(
        json.dumps(payload["profile"], indent=4)
    )
    (base / "settings.json").write_text(
        json.dumps(payload["settings"], indent=4)
    )
    (base / "knowledge.txt").write_text(payload["knowledge"])

    return {"message": "Business updated"}

# -----------------------------
# -----------------------------
# Step 16 — Analytics Route (role protected)
# -----------------------------
@app.get("/analytics/{business_id}")
def analytics(
    business_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_subscription(user)
    require_role(user, ["owner", "admin", "staff"])

    business = (
        db.query(Business)
        .filter(Business.folder_name == business_id)
        .first()
    )

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    logs = (
        db.query(MessageLog)
        .filter(MessageLog.business_id == business.id)
        .all()
    )

    return {
        "total_messages": len(logs),
        "messages_this_month": count_messages_this_month(db, business.id),
        "history": [
            {
                "timestamp": log.timestamp,
                "user_message": log.user_message,
                "bot_response": log.bot_response,
            }
            for log in logs
        ],
    }


# -----------------------------
# Step 20 — Export Routes
# -----------------------------
@app.get("/export/conversation/{convo_id}")
def export_conversation(
    convo_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    convo = db.query(Conversation).filter(
        Conversation.id == convo_id,
        Conversation.business_id == user.business_id
    ).first()

    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    logs = db.query(MessageLog).filter(
        MessageLog.conversation_id == convo_id
    ).order_by(MessageLog.timestamp.asc()).all()

    csv_data = "timestamp,user_message,bot_response\n"
    for log in logs:
        csv_data += f"{log.timestamp},{log.user_message},{log.bot_response}\n"

    return csv_data


@app.get("/export/all")
def export_all(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    business_id = user.business_id

    logs = db.query(MessageLog).filter(
        MessageLog.business_id == business_id
    ).order_by(MessageLog.timestamp.asc()).all()

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
    db: Session = Depends(get_db)
):
    business_id = user.business_id
    convo_ids = payload["conversation_ids"]

    logs = db.query(MessageLog).filter(
        MessageLog.business_id == business_id,
        MessageLog.conversation_id.in_(convo_ids)
    ).order_by(MessageLog.timestamp.asc()).all()

    csv_data = "conversation_id,timestamp,user_message,bot_response\n"
    for log in logs:
        csv_data += (
            f"{log.conversation_id},{log.timestamp},"
            f"{log.user_message},{log.bot_response}\n"
        )

    return csv_data


# -----------------------------
# Stripe Webhook
# -----------------------------
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

    # -----------------------------
    # 1. Handle checkout completion
    # -----------------------------
    if event_type == "checkout.session.completed":
        email = data.get("customer_email")
        user = db.query(User).filter(User.email == email).first()

        if user:
            user.subscription_active = 1
            db.commit()
            print("Subscription activated for:", email)

    # -----------------------------
    # 2. Handle payment failure
    # -----------------------------
    if event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()

        if user:
            from .email_utils import send_email
            send_email(
                to_email=user.email,
                subject="Payment Failed",
                body="Your recent payment failed. Please update your billing information."
            )

    # -----------------------------
    # 3. Handle subscription canceled
    # -----------------------------
    if event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()

        if user:
            from .email_utils import send_email
            send_email(
                to_email=user.email,
                subject="Subscription Canceled",
                body="Your subscription has been canceled. Your chatbot is now inactive."
            )

    return {"status": "success"}


