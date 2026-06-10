from sqlalchemy import Boolean, Column, Integer, String, ForeignKey, false
from sqlalchemy.orm import relationship
from database import Base  # FIXED: removed the dot

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    is_admin = Column(Boolean, nullable=False, default=False, server_default=false())
    businesses = relationship("Business", back_populates="owner")

class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    folder_name = Column(String, unique=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="businesses")