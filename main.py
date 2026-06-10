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
from sqlalchemy import func, inspect
from sqlalchemy.exc import SQLAlchemyError

# Database + models
from database import Base, engine, SessionLocal
from sqlalchemy.orm import Session
from models import User, Business

# Auth utilities
from auth_utils import (
    create_access_token,
    get_current_admin_user,
    get_current_user,
    hash_password,
    parse_admin_emails,
    user_has_admin_access,
    verify_password,
)

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


def ensure_user_admin_column():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "is_admin" in user_columns:
        return

    default_value = "0" if engine.dialect.name == "sqlite" else "FALSE"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT {default_value}"
        )


def apply_admin_email_allowlist():
    admin_emails = parse_admin_emails()
    if not admin_emails:
        return

    db = SessionLocal()
    try:
        users = db.query(User).filter(func.lower(User.email).in_(admin_emails)).all()
        updated = False
        for user in users:
            if not user.is_admin:
                user.is_admin = True
                updated = True

        if updated:
            db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while applying ADMIN_EMAILS allowlist")
    finally:
        db.close()


# Create database tables
Base.metadata.create_all(bind=engine)
ensure_user_admin_column()
apply_admin_email_allowlist()

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


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str):
    normalized_email = normalize_email(email)
    try:
        return db.query(User).filter(func.lower(User.email) == normalized_email).first()
    except SQLAlchemyError:
        logger.exception("Database error while looking up user during login")
        raise HTTPException(status_code=500, detail="Unable to complete login")


def is_admin_email(email: str) -> bool:
    return normalize_email(email) in parse_admin_emails()


def sync_allowlisted_admin(db: Session, user: User) -> bool:
    if is_admin_email(user.email) and not user.is_admin:
        try:
            user.is_admin = True
            db.commit()
            db.refresh(user)
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Database error while promoting allowlisted admin user")
            raise HTTPException(status_code=500, detail="Unable to complete login")

    return user_has_admin_access(user)


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


def get_business_summaries_for_user(db: Session, user_id: int, *, fail_on_error: bool = True):
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


def serialize_admin_business_summary(business, owner_email):
    summary = serialize_business_summary(business)
    if summary is None:
        return None

    summary.update(
        {
            "owner_id": business.owner_id,
            "owner_email": owner_email,
        }
    )
    return summary

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
    return get_business_summaries_for_user(db, user.id)


@app.get("/admin/businesses")
def admin_businesses(admin_user = Depends(get_current_admin_user), db: Session = Depends(get_db)):
    try:
        rows = (
            db.query(Business, User.email)
            .outerjoin(User, Business.owner_id == User.id)
            .all()
        )
    except SQLAlchemyError:
        logger.exception("Database error while loading admin businesses")
        raise HTTPException(status_code=500, detail="Unable to load businesses")

    businesses = []
    for business, owner_email in rows:
        summary = serialize_admin_business_summary(business, owner_email)
        if summary is not None:
            businesses.append(summary)

    return businesses


@app.get("/admin/analytics")
def admin_analytics(admin_user = Depends(get_current_admin_user), db: Session = Depends(get_db)):
    try:
        return {
            "users": db.query(func.count(User.id)).scalar() or 0,
            "businesses": db.query(func.count(Business.id)).scalar() or 0,
            "admins": db.query(func.count(User.id)).filter(User.is_admin.is_(True)).scalar() or 0,
        }
    except SQLAlchemyError:
        logger.exception("Database error while loading admin analytics")
        raise HTTPException(status_code=500, detail="Unable to load analytics")


# Step 11B - Protected business loader
@app.get("/business/{business_id}")
def get_business(business_id: str, user = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        business = db.query(Business).filter(Business.folder_name == business_id).first()
    except SQLAlchemyError:
        logger.exception("Database error while loading business_id=%s", business_id)
        raise HTTPException(status_code=500, detail="Unable to load business")

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
    try:
        owner = db.query(User).filter(User.id == req.owner_id).first()
    except SQLAlchemyError:
        logger.exception("Database error while loading owner_id=%s", req.owner_id)
        raise HTTPException(status_code=500, detail="Unable to create business")

    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")

    new_business = create_business_for_user(
        db=db,
        user=owner,
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
    email = normalize_email(req.email)
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.exception("Database error while checking signup email")
        raise HTTPException(status_code=500, detail="Unable to complete signup")

    user = User(
        email=email,
        password_hash=hash_password(req.password),
        is_admin=is_admin_email(email),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # NEW: create business automatically
    create_business_for_user(db, user, req.business_name)

    return {"message": "Signup successful"}

@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, req.email)

    password_is_valid = False
    if user:
        try:
            password_is_valid = verify_password(req.password, user.password_hash)
        except Exception:
            logger.exception("Password verification failed for user_id=%s", user.id)

    if not user or not password_is_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    is_admin = sync_allowlisted_admin(db, user)
    token = create_access_token({"user_id": user.id, "is_admin": is_admin})
    businesses = get_business_summaries_for_user(db, user.id, fail_on_error=False)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "is_admin": is_admin,
        "businesses": businesses,
    }

# -----------------------------
# Step 11C - Protected Update Business
# -----------------------------
@app.post("/update_business")
def update_business(payload: dict, user = Depends(get_current_user), db: Session = Depends(get_db)):
    business_id = payload.get("business_id")
    if not business_id:
        raise HTTPException(status_code=400, detail="business_id is required")

    try:
        business = db.query(Business).filter(Business.folder_name == business_id).first()
    except SQLAlchemyError:
        logger.exception("Database error while loading business_id=%s for update", business_id)
        raise HTTPException(status_code=500, detail="Unable to update business")

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
