from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

from database import SessionLocal
from models import User


# ============================
# PASSWORD HASHING
# ============================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================
# JWT CONFIG
# ============================
SECRET_KEY = "18002672001201108"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ============================
# AUTHENTICATION
# ============================
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")

        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ============================
# ROLE GUARD
# ============================
def require_role(user: User, allowed_roles: list[str]):
    """
    Ensure the current user has one of the allowed roles.
    Raises HTTPException(403) if not authorized.
    """
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Not authorized")
