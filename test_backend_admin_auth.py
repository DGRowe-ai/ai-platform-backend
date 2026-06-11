import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "backend_admin_auth_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["OPENAI_API_KEY"] = "test-openai-key"

from fastapi.testclient import TestClient

import main
from auth_utils import hash_password
from database import Base, SessionLocal, engine
from models import AuditLog, Business, User


class BackendAdminAuthTests(unittest.TestCase):
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
            password_hash=hash_password("password"),
            role="owner",
            subscription_active=1,
        )
        self.business_admin_user = User(
            email="business-admin@example.com",
            password_hash=hash_password("password"),
            role="admin",
            subscription_active=1,
        )
        self.db.add_all([self.admin_user, self.client_user, self.business_admin_user])
        self.db.commit()
        self.db.refresh(self.admin_user)
        self.db.refresh(self.client_user)
        self.db.refresh(self.business_admin_user)

        self.admin_business = Business(
            name="Admin Business",
            folder_name="admin_business",
            owner_id=self.admin_user.id,
        )
        self.client_business = Business(
            name="Client Business",
            folder_name="client_business",
            owner_id=self.client_user.id,
        )
        self.business_admin_business = Business(
            name="Business Admin Business",
            folder_name="business_admin_business",
            owner_id=self.business_admin_user.id,
        )
        self.db.add_all(
            [self.admin_business, self.client_business, self.business_admin_business]
        )
        self.db.commit()
        self.db.refresh(self.client_business)

        self.client_user.business_id = self.client_business.id
        self.business_admin_user.business_id = self.business_admin_business.id
        self.db.add(AuditLog(user_id=self.admin_user.id, event_type="signup", description="test"))
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

    def test_allowlisted_user_is_promoted_and_can_access_admin_routes(self):
        login_response = self.login("admin@example.com")

        self.assertEqual(login_response["role"], "owner")
        self.assertEqual(login_response["business_role"], "owner")
        self.assertNotIn("is_admin", login_response)
        self.assertTrue(login_response["is_platform_admin"])

        headers = self.auth_headers(login_response["access_token"])
        businesses_response = self.client.get("/admin/businesses", headers=headers)
        analytics_response = self.client.get("/admin/analytics", headers=headers)

        self.assertEqual(businesses_response.status_code, 200)
        self.assertEqual(analytics_response.status_code, 200)
        self.assertEqual(len(businesses_response.json()), 3)

    def test_non_admin_is_forbidden_but_my_businesses_still_works(self):
        login_response = self.login("client@example.com")

        self.assertEqual(login_response["role"], "owner")
        self.assertNotIn("is_admin", login_response)
        self.assertFalse(login_response["is_platform_admin"])

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
                    "id": self.client_business.id,
                    "name": "Client Business",
                    "folder_name": "client_business",
                }
            ],
        )

    def test_business_admin_role_does_not_get_platform_admin_redirect_signal(self):
        login_response = self.login("business-admin@example.com")

        self.assertEqual(login_response["role"], "business_admin")
        self.assertEqual(login_response["business_role"], "admin")
        self.assertNotIn("is_admin", login_response)
        self.assertFalse(login_response["is_platform_admin"])

        headers = self.auth_headers(login_response["access_token"])
        businesses_response = self.client.get("/admin/businesses", headers=headers)
        analytics_response = self.client.get("/admin/analytics", headers=headers)
        client_dashboard_response = self.client.get("/client/dashboard", headers=headers)

        self.assertEqual(businesses_response.status_code, 403)
        self.assertEqual(analytics_response.status_code, 403)
        self.assertEqual(client_dashboard_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
