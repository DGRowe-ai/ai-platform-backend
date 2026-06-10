import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "admin_auth_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@example.com"

from fastapi.testclient import TestClient

import main
from auth_utils import hash_password
from database import Base, SessionLocal, engine
from models import Business, User


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        main.ensure_user_admin_column()

        self.db = SessionLocal()
        self.admin_user = User(
            email="admin@example.com",
            password_hash=hash_password("password"),
        )
        self.client_user = User(
            email="client@example.com",
            password_hash=hash_password("password"),
        )
        self.db.add_all([self.admin_user, self.client_user])
        self.db.commit()
        self.db.refresh(self.admin_user)
        self.db.refresh(self.client_user)

        self.db.add_all(
            [
                Business(
                    name="Admin Business",
                    folder_name="admin_business",
                    owner_id=self.admin_user.id,
                ),
                Business(
                    name="Client Business",
                    folder_name="client_business",
                    owner_id=self.client_user.id,
                ),
            ]
        )
        self.db.commit()

        self.client = TestClient(main.app)

    def tearDown(self):
        self.db.close()

    def login(self, email):
        response = self.client.post(
            "/login",
            json={"email": email, "password": "password"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    @staticmethod
    def auth_headers(token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_user_can_access_admin_routes(self):
        login_response = self.login("admin@example.com")

        self.assertTrue(login_response["is_admin"])

        headers = self.auth_headers(login_response["access_token"])
        businesses_response = self.client.get("/admin/businesses", headers=headers)
        analytics_response = self.client.get("/admin/analytics", headers=headers)

        self.assertEqual(businesses_response.status_code, 200)
        self.assertEqual(analytics_response.status_code, 200)
        self.assertEqual(len(businesses_response.json()), 2)
        self.assertEqual(analytics_response.json()["businesses"], 2)

    def test_non_admin_user_is_forbidden_but_my_businesses_still_works(self):
        login_response = self.login("client@example.com")

        self.assertFalse(login_response["is_admin"])

        headers = self.auth_headers(login_response["access_token"])
        businesses_response = self.client.get("/admin/businesses", headers=headers)
        analytics_response = self.client.get("/admin/analytics", headers=headers)
        my_businesses_response = self.client.get("/my_businesses", headers=headers)

        self.assertEqual(businesses_response.status_code, 403)
        self.assertEqual(analytics_response.status_code, 403)
        self.assertEqual(my_businesses_response.status_code, 200)
        self.assertEqual(
            my_businesses_response.json(),
            [
                {
                    "id": 2,
                    "name": "Client Business",
                    "folder_name": "client_business",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
