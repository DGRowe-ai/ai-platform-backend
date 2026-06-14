"""One-time migration: assign rowe_ai_website to rowe-ai@outlook.com and copy knowledge."""

from admin_business_ops import run_rowe_website_owner_migration
from database import SessionLocal


def main():
    with SessionLocal() as db:
        result = run_rowe_website_owner_migration(db)
        print(result)


if __name__ == "__main__":
    main()
