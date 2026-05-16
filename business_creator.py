import shutil
from pathlib import Path
from sqlalchemy.orm import Session
from models import Business

TEMPLATE_PATH = Path("../businesses/template")
BUSINESSES_PATH = Path("../businesses")

def create_business(db: Session, owner_id: int, business_name: str):
    # 1. Create a folder name based on the business name
    folder_name = business_name.lower().replace(" ", "_")

    # 2. Create the new business folder path
    new_business_path = BUSINESSES_PATH / folder_name

    # 3. Copy the template folder
    shutil.copytree(TEMPLATE_PATH, new_business_path)

    # 4. Insert into database
    new_business = Business(
        name=business_name,
        folder_name=folder_name,
        owner_id=owner_id
    )

    db.add(new_business)
    db.commit()
    db.refresh(new_business)

    return new_business