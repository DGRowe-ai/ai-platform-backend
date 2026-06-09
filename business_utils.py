import shutil
from pathlib import Path
from sqlalchemy.orm import Session
from models import Business
import logging

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path("..") / "businesses" / "template"
BUSINESSES_PATH = Path("..") / "businesses"

def create_business_for_user(db: Session, user, business_name: str):
    """Create a new business folder for a user by copying the template"""
    try:
        # Validate inputs
        if not user or not business_name:
            raise ValueError("User and business_name are required")
        
        # Create folder name from business name
        folder_name = business_name.lower().replace(" ", "_").replace("-", "_")
        new_path = BUSINESSES_PATH / folder_name
        
        # Check if business already exists
        if new_path.exists():
            raise Exception(f"Business folder already exists: {folder_name}")
        
        # Check if template exists
        if not TEMPLATE_PATH.exists():
            raise Exception(f"Template folder not found: {TEMPLATE_PATH}")
        
        # Copy template to new business folder
        logger.info(f"Creating business folder: {folder_name}")
        shutil.copytree(TEMPLATE_PATH, new_path)
        
        # Create database record
        business = Business(
            name=business_name,
            folder_name=folder_name,
            owner_id=user.id
        )
        
        db.add(business)
        db.commit()
        db.refresh(business)
        
        logger.info(f"Business created successfully: {folder_name} (ID: {business.id})")
        return business
    
    except Exception as e:
        logger.error(f"Error creating business for user {user.id}: {str(e)}")
        db.rollback()
        raise
