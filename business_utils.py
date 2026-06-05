import os
import shutil
from pathlib import Path
from models import Business

# Always resolve paths relative to THIS file (works on Render)
BASE_DIR = Path(__file__).resolve().parent

# Businesses folder inside src (this is writable on Render)
BUSINESSES_PATH = BASE_DIR / "businesses"

# Template folder inside businesses
TEMPLATE_PATH = BUSINESSES_PATH / "template"

def create_business_for_user(db, user, business_name):
    # Convert business name to folder-safe format
    folder_name = business_name.lower().replace(" ", "_")
    new_path = BUSINESSES_PATH / folder_name

    # Ensure businesses directory exists
    BUSINESSES_PATH.mkdir(parents=True, exist_ok=True)

    # Prevent overwriting existing business
    if new_path.exists():
        raise Exception("Business folder already exists")

    # Copy template folder into new business folder
    shutil.copytree(TEMPLATE_PATH, new_path)

    # Create DB entry
    business = Business(
        name=business_name,
        folder_name=folder_name,
        owner_id=user.id
    )

    db.add(business)
    db.commit()
    db.refresh(business)

    return business
