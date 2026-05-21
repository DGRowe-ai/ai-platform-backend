from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    subscription_active = Column(Integer, default=0)

    # Step 17 fields
    role = Column(String, default="owner")
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)

    # FIX: specify foreign_keys so SQLAlchemy knows which FK belongs to this relationship
    businesses = relationship(
        "Business",
        back_populates="owner",
        foreign_keys="Business.owner_id"
    )

class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    folder_name = Column(String, unique=True)

    owner_id = Column(Integer, ForeignKey("users.id"))

    # FIX: specify foreign_keys here too
    owner = relationship(
        "User",
        back_populates="businesses",
        foreign_keys=[owner_id]
    )
