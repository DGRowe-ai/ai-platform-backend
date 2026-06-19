import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "referral_system_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["OPENAI_API_KEY"] = "test-openai-key"

from fastapi.testclient import TestClient

import main
from auth_utils import hash_password, normalize_email
from database import Base, SessionLocal, engine
from models import User
from referral_utils import (
    apply_referral_on_signup,
    build_referral_link,
    ensure_user_referral_code,
    generate_unique_referral_code,
)


class ReferralSystemTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        self.db = SessionLocal()
        self.referrer = User(
            email="referrer@example.com",
            password_hash=hash_password("password123"),
            role="owner",
            subscription_active=1,
            stripe_customer_id="cus_referrer",
        )
        self.db.add(self.referrer)
        self.db.commit()
        self.db.refresh(self.referrer)
        self.referrer.referral_code = generate_unique_referral_code(self.db)
        self.db.add(self.referrer)
        self.db.commit()
        self.db.refresh(self.referrer)

        self.client = TestClient(main.app)

    def tearDown(self):
        self.db.close()

    def test_generate_unique_referral_code(self):
        code = generate_unique_referral_code(self.db)
        self.assertTrue(len(code) >= 8)

    def test_build_referral_link(self):
        link = build_referral_link("abc123")
        self.assertIn("abc123", link)
        self.assertIn("ref=", link)

    def test_apply_referral_blocks_self_referral(self):
        new_user = User(
            email="referrer@example.com",
            password_hash=hash_password("password123"),
            role="owner",
            id=self.referrer.id,
        )
        result = apply_referral_on_signup(
            self.db,
            new_user=new_user,
            referral_code=self.referrer.referral_code,
        )
        self.assertIsNone(result)

    def test_apply_referral_links_new_user(self):
        new_user = User(
            email="newclient@example.com",
            password_hash=hash_password("password123"),
            role="owner",
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)

        referrer = apply_referral_on_signup(
            self.db,
            new_user=new_user,
            referral_code=self.referrer.referral_code,
            signup_ip="203.0.113.10",
        )
        self.assertIsNotNone(referrer)
        self.assertEqual(new_user.referred_by_user_id, self.referrer.id)

    def test_request_password_reset_style_generic_response_for_referral_lookup(self):
        new_user = User(
            email="brandnew@example.com",
            password_hash=hash_password("password123"),
            role="owner",
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        ensure_user_referral_code(self.db, new_user)
        self.assertTrue(new_user.referral_code)


if __name__ == "__main__":
    unittest.main()
