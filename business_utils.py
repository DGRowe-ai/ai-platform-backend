import shutil
from pathlib import Path
from models import Business

TEMPLATE_PATH = Path("..") / "businesses" / "template"
BUSINESSES_PATH = Path("..") / "businesses"

def create_business_for_user(db, user, business_name):
    folder_name = business_name.lower().replace(" ", "_")
    new_path = BUSINESSES_PATH / folder_name

    if new_path.exists():
        raise Exception("Business folder already exists")

    shutil.copytree(TEMPLATE_PATH, new_path)

    business = Business(
        name=business_name,
        folder_name=folder_name,
        owner_id=user.id
    )

    db.add(business)
    db.commit()
    db.refresh(business)

    return business
