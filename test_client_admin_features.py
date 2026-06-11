import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "client_admin_features_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["OPENAI_API_KEY"] = "test-openai-key"

from fastapi.testclient import TestClient

import main
from auth_utils import hash_password, verify_password
from business_utils import BUSINESSES_PATH, create_business_for_user
from database import Base, SessionLocal, engine
from models import Business, User


class ClientAdminFeatureTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.db = SessionLocal()
        self.admin_user = User(
            email="admin@example.com",
            password_hash=hash_password("password"),
            role="owner",
            subscription_active=1,
        )
        self.client_user = User(
            email="client@example.com",
            password_hash=hash_password("starter123"),
            role="owner",
            subscription_active=1,
        )
        self.db.add_all([self.admin_user, self.client_user])
        self.db.commit()
        self.db.refresh(self.admin_user)
        self.db.refresh(self.client_user)

        self.client_business = create_business_for_user(
            self.db, self.client_user, f"Delete Me Shop {self.id()}"
        )
        self.client_user.business_id = self.client_business.id
        self.db.add(self.client_user)
        self.db.commit()

        self.client = TestClient(main.app)

    def tearDown(self):
        self.db.close()

    def login(self, email):
        response = self.client.post(
            "/login",
            json={"email": email, "password": "password" if email == "admin@example.com" else "starter123"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    @staticmethod
    def auth_headers(token):
        return {"Authorization": f"Bearer {token}"}

    def test_owner_can_change_password(self):
        login_response = self.login("client@example.com")
        headers = self.auth_headers(login_response["access_token"])

        response = self.client.post(
            "/client/change_password",
            headers=headers,
            json={
                "current_password": "starter123",
                "new_password": "newsecurepass",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(self.client_user)
        self.assertTrue(verify_password("newsecurepass", self.client_user.password_hash))

    def test_admin_can_delete_business(self):
        folder_name = self.client_business.folder_name
        login_response = self.login("admin@example.com")
        headers = self.auth_headers(login_response["access_token"])

        response = self.client.delete(
            f"/admin/businesses/{folder_name}",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.db.query(Business).filter(Business.folder_name == folder_name).first())
        self.assertFalse((BUSINESSES_PATH / folder_name).exists())
        self.assertIsNone(self.db.query(User).filter(User.email == "client@example.com").first())

    def test_non_admin_cannot_delete_business(self):
        login_response = self.login("client@example.com")
        headers = self.auth_headers(login_response["access_token"])

        response = self.client.delete(
            f"/admin/businesses/{self.client_business.folder_name}",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
