from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
import json
import logging
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

# Load environment variables
load_dotenv()
logger = logging.getLogger(__name__)

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

# FastAPI app
app = FastAPI()

# Create database tables
Base.metadata.create_all(bind=engine)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error during %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

openai_client = None


def get_openai_client():
    global openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured for chat responses",
        )

    if openai_client is None:
        openai_client = OpenAI(api_key=api_key)

    return openai_client

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
    base = Path("..") / "businesses" / business_id

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
    business_name: str   # <-- Step 12 addition

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

Respond clearly, accurately, and only using the business information above.
"""

    response = get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=business_data["settings"]["max_response_length"]
    )

    return response.choices[0].message.content

# -----------------------------
# Routes
# -----------------------------
@app.get("/ping")
def ping():
    return {"message": "pong"}

# Step 11A - Get logged-in user's businesses
@app.get("/my_businesses")
def my_businesses(user = Depends(get_current_user), db: Session = Depends(get_db)):
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
def create_business_route(req: CreateBusinessRequest, db: Session = Depends(get_db)):
    new_business = create_business_for_user(
        db=db,
        user=db.query(User).filter(User.id == req.owner_id).first(),
        business_name=req.business_name
    )
    return {
        "message": "Business created successfully",
        "business_id": new_business.folder_name
    }

@app.post("/chat")
def chat(req: ChatRequest):
    data = load_business_data(req.business_id)
    ai_response = generate_ai_response(data, req.message)
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
        password_hash=hash_password(req.password)
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # NEW: create business automatically
    create_business_for_user(db, user, req.business_name)

    return {"message": "Signup successful"}

@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()

    password_is_valid = False
    if user:
        try:
            password_is_valid = verify_password(req.password, user.password_hash)
        except Exception:
            logger.exception("Password verification failed for user_id=%s", user.id)

    if not user or not password_is_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": user.id})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id
    }

# -----------------------------
# Step 11C - Protected Update Business
# -----------------------------
@app.post("/update_business")
def update_business(payload: dict, user = Depends(get_current_user), db: Session = Depends(get_db)):
    business_id = payload["business_id"]

    business = db.query(Business).filter(Business.folder_name == business_id).first()

    if not business or business.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    base = Path("..") / "businesses" / business_id

    (base / "profile.json").write_text(json.dumps(payload["profile"], indent=4))
    (base / "settings.json").write_text(json.dumps(payload["settings"], indent=4))
    (base / "knowledge.txt").write_text(payload["knowledge"])

    return {"message": "Business updated"}


# Keep CORS as the outermost ASGI layer so even 500 responses include CORS
# headers and browsers show the real JSON error instead of masking it.
app = CORSMiddleware(
    app=app,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
