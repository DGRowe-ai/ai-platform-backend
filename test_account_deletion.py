import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "account_deletion_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["OPENAI_API_KEY"] = "test-openai-key"

from fastapi.testclient import TestClient

import main
from auth_utils import create_access_token, hash_password
from business_utils import create_business_for_user
from database import Base, SessionLocal, engine
from models import User


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.db = SessionLocal()
        self.user = User(
            email="client@example.com",
            password_hash=hash_password("password123"),
            role="owner",
            subscription_active=1,
            stripe_customer_id="cus_test123",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.business = create_business_for_user(self.db, self.user, "Delete Me Shop")
        self.user.business_id = self.business.id
        self.db.add(self.user)
        self.db.commit()

        self.token = create_access_token({"user_id": self.user.id})
        self.client = TestClient(main.app)

    def tearDown(self):
        self.db.close()

    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_owner_can_delete_account(self):
        with unittest.mock.patch(
            "account_deletion_utils.cancel_user_stripe_subscriptions",
            return_value=["sub_test"],
        ):
            with unittest.mock.patch("account_routes.send_account_deleted_user_email"):
                with unittest.mock.patch("account_routes.send_account_deleted_admin_email"):
                    response = self.client.delete(
                        "/api/account/delete",
                        headers=self.auth_headers(),
                    )

        self.assertEqual(response.status_code, 200)
        self.assertIn("deleted", response.json()["message"].lower())
        self.assertIsNone(
            self.db.query(User).filter(User.email == "client@example.com").first()
        )

    def test_unauthenticated_cannot_delete_account(self):
        response = self.client.delete("/api/account/delete")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
