import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

TEST_DB = Path(tempfile.gettempdir()) / "stripe_checkout_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_example"
os.environ["STRIPE_PRICE_ID"] = "price_test_123"
os.environ["BACKEND_PUBLIC_URL"] = "https://api.example.com"
os.environ["FRONTEND_PUBLIC_URL"] = "https://app.example.com"

from fastapi.testclient import TestClient

import main
from auth_utils import hash_password
from business_utils import create_business_for_user
from database import Base, SessionLocal, engine
from models import User
from stripe_checkout_utils import build_checkout_activation_url


class StripeCheckoutTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        main.ensure_user_stripe_schema()

        self.db = SessionLocal()
        self.user = User(
            email="billing@example.com",
            password_hash=hash_password("password"),
            role="owner",
            subscription_active=0,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.business = create_business_for_user(
            self.db,
            self.user,
            f"Billing Test Shop {uuid.uuid4().hex[:8]}",
        )
        self.user.business_id = self.business.id
        self.db.add(self.user)
        self.db.commit()

        self.client = TestClient(main.app, follow_redirects=False)

    def tearDown(self):
        self.db.close()

    def test_build_checkout_activation_url(self):
        url = build_checkout_activation_url("billing@example.com")
        self.assertEqual(
            url,
            "https://api.example.com/create-checkout-session?email=billing%40example.com",
        )

    @patch("stripe_checkout_utils.stripe.checkout.Session.create")
    @patch("stripe_checkout_utils.stripe.Customer.create")
    def test_create_checkout_session_redirects_by_email(
        self,
        mock_customer_create,
        mock_session_create,
    ):
        mock_customer_create.return_value = MagicMock(id="cus_test_123")
        mock_session_create.return_value = MagicMock(
            url="https://checkout.stripe.com/pay/cs_test_123"
        )

        response = self.client.get(
            "/create-checkout-session",
            params={"email": "billing@example.com"},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "https://checkout.stripe.com/pay/cs_test_123",
        )

        self.db.refresh(self.user)
        self.assertEqual(self.user.stripe_customer_id, "cus_test_123")
        mock_session_create.assert_called_once()

    @patch("stripe_checkout_utils.stripe.checkout.Session.create")
    def test_create_checkout_session_redirects_by_business_id(
        self,
        mock_session_create,
    ):
        self.user.stripe_customer_id = "cus_existing_123"
        self.db.add(self.user)
        self.db.commit()

        mock_session_create.return_value = MagicMock(
            url="https://checkout.stripe.com/pay/cs_test_456"
        )

        response = self.client.get(
            "/create-checkout-session",
            params={"business_id": self.business.folder_name},
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "https://checkout.stripe.com/pay/cs_test_456",
        )


if __name__ == "__main__":
    unittest.main()
