import os
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "password_reset_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-for-reset"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["PASSWORD_RESET_BASE_URL"] = "https://roweai.ca"

from fastapi.testclient import TestClient

import main
from auth_utils import hash_password, verify_password
from database import Base, SessionLocal, engine
from models import User
from password_reset_utils import hash_reset_token


class PasswordResetTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.db = SessionLocal()
        self.user = User(
            email="client@example.com",
            password_hash=hash_password("oldpassword123"),
            role="owner",
            subscription_active=1,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.client = TestClient(main.app)

    def tearDown(self):
        self.db.close()

    def test_request_reset_always_returns_generic_success(self):
        with unittest.mock.patch("auth_routes.send_password_reset_email") as send_email:
            response = self.client.post(
                "/api/auth/request-password-reset",
                json={"email": "client@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("If this email exists", response.json()["message"])
        send_email.assert_called_once()

        self.db.refresh(self.user)
        self.assertTrue(self.user.password_reset_token_hash)
        self.assertTrue(self.user.password_reset_expires_at)

    def test_request_reset_unknown_email_still_returns_success(self):
        with unittest.mock.patch("auth_routes.send_password_reset_email") as send_email:
            response = self.client.post(
                "/api/auth/request-password-reset",
                json={"email": "missing@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        send_email.assert_not_called()

    def test_reset_password_with_valid_token(self):
        raw_token = "test-reset-token-value"
        self.user.password_reset_token_hash = hash_reset_token(raw_token)
        self.user.password_reset_expires_at = datetime.utcnow() + timedelta(minutes=30)
        self.db.add(self.user)
        self.db.commit()

        response = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "newPassword": "newsecurepass"},
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(self.user)
        self.assertIsNone(self.user.password_reset_token_hash)
        self.assertIsNone(self.user.password_reset_expires_at)
        self.assertTrue(verify_password("newsecurepass", self.user.password_hash))

    def test_reset_password_rejects_expired_token(self):
        raw_token = "expired-reset-token"
        self.user.password_reset_token_hash = hash_reset_token(raw_token)
        self.user.password_reset_expires_at = datetime.utcnow() - timedelta(minutes=1)
        self.db.add(self.user)
        self.db.commit()

        response = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "newPassword": "newsecurepass"},
        )

        self.assertEqual(response.status_code, 400)

    def test_validate_reset_token(self):
        raw_token = "valid-token"
        self.user.password_reset_token_hash = hash_reset_token(raw_token)
        self.user.password_reset_expires_at = datetime.utcnow() + timedelta(minutes=10)
        self.db.add(self.user)
        self.db.commit()

        response = self.client.post(
            "/api/auth/validate-reset-token",
            json={"token": raw_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])


if __name__ == "__main__":
    unittest.main()
