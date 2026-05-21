from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    subscription_active = Column(Integer, default=0)

    # ⭐ Step 17 fields
    role = Column(String, default="owner")  # owner, admin, staff
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)

    # Relationships
    businesses = relationship("Business", back_populates="owner")

class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    folder_name = Column(String, unique=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="businesses")

    # ⭐ Step 17: allow multiple users
    users = relationship("User", backref="business")

class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    timestamp = Column(String)
    user_message = Column(String)
    bot_response = Column(String)
