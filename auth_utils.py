from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.exc import SQLAlchemyError
from database import SessionLocal
from models import User
import os
import logging

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Get SECRET_KEY from environment, with a fallback for development
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_TO_A_LONG_RANDOM_STRING_IN_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def parse_admin_emails():
    """Return the normalized ADMIN_EMAILS allowlist."""
    configured_emails = os.getenv("ADMIN_EMAILS", "")
    return {
        normalize_email(email)
        for email in configured_emails.split(",")
        if email.strip()
    }


def is_admin_email(email: str) -> bool:
    return normalize_email(email) in parse_admin_emails()


def user_has_role(user: User, allowed_roles: list) -> bool:
    normalized_allowed_roles = {
        role.strip().lower()
        for role in allowed_roles
        if role and role.strip()
    }
    user_role = (user.role or "").strip().lower()

    if user_role in normalized_allowed_roles:
        return True

    return "admin" in normalized_allowed_roles and is_admin_email(user.email)


def sync_admin_role_from_allowlist(db, user: User) -> User:
    """Promote allowlisted users into the existing role-based admin system."""
    if is_admin_email(user.email) and (user.role or "").strip().lower() != "admin":
        try:
            user.role = "admin"
            db.commit()
            db.refresh(user)
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Database error while promoting allowlisted admin user")
            raise HTTPException(status_code=500, detail="Unable to complete login")

    return user


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt"""
    try:
        return pwd_context.hash(password)
    except Exception:
        logger.exception("Password hashing failed")
        raise HTTPException(status_code=500, detail="Unable to secure password")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its hash"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        logger.exception("Password hash verification failed")
        return False


def create_access_token(data: dict) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)):
    """Dependency to get the current authenticated user"""
    db = None
    try:
        # Decode the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")

        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Get user from database
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user

    except HTTPException:
        raise
    except JWTError as e:
        logger.error("JWT decode error: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid token")
    except SQLAlchemyError:
        logger.exception("Database error while loading current user")
        raise HTTPException(status_code=500, detail="Unable to authenticate user")
    except Exception as e:
        logger.exception("Error in get_current_user: %s", str(e))
        raise HTTPException(status_code=401, detail="Authentication failed")
    finally:
        # Always close the database connection
        if db:
            db.close()


def require_role(user: User, allowed_roles: list):
    """
    Ensure the current user has one of the allowed roles.
    Raises HTTPException(403) if not authorized.
    """
    if not user_has_role(user, allowed_roles):
        raise HTTPException(status_code=403, detail="Not authorized")
