import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

TEST_DB = Path(tempfile.gettempdir()) / "review_email_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"

from database import Base, SessionLocal, engine
from models import AuditLog, Business, User
from review_email_utils import (
    REVIEW_EMAIL_DELAY_DAYS,
    find_users_due_for_review_email,
    user_is_eligible_for_review_email,
)


class ReviewEmailUtilsTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()

        self.user = User(
            email="client@example.com",
            password_hash="hash",
            role="owner",
            subscription_active=1,
            billing_status="active",
            registered_at=datetime.utcnow() - timedelta(days=REVIEW_EMAIL_DELAY_DAYS + 1),
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        business = Business(
            name="Test Shop",
            folder_name="test_shop",
            owner_id=self.user.id,
            phone="(555) 123-4567",
        )
        self.db.add(business)
        self.db.commit()
        self.db.refresh(business)

        self.user.business_id = business.id
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.close()

    def test_user_is_eligible_after_one_week(self):
        self.assertTrue(user_is_eligible_for_review_email(self.db, self.user))

    def test_user_not_eligible_before_one_week(self):
        self.user.registered_at = datetime.utcnow() - timedelta(days=2)
        self.db.add(self.user)
        self.db.commit()
        self.assertFalse(user_is_eligible_for_review_email(self.db, self.user))

    def test_user_not_eligible_after_email_sent(self):
        self.user.review_request_email_sent_at = datetime.utcnow()
        self.db.add(self.user)
        self.db.commit()
        self.assertFalse(user_is_eligible_for_review_email(self.db, self.user))

    def test_find_users_due_for_review_email(self):
        due = find_users_due_for_review_email(self.db)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].email, "client@example.com")

    def test_fallback_to_signup_audit_log(self):
        self.user.registered_at = None
        self.db.add(self.user)
        self.db.commit()

        log = AuditLog(
            user_id=self.user.id,
            event_type="signup",
            description="New user registered",
            timestamp=datetime.utcnow() - timedelta(days=REVIEW_EMAIL_DELAY_DAYS + 2),
        )
        self.db.add(log)
        self.db.commit()

        self.assertTrue(user_is_eligible_for_review_email(self.db, self.user))

    @mock.patch("review_email_utils.send_review_request_email")
    def test_process_review_request_emails(self, mock_send):
        from review_email_utils import process_review_request_emails

        result = process_review_request_emails(self.db)
        self.assertEqual(result["sent"], 1)
        mock_send.assert_called_once()

        self.db.refresh(self.user)
        self.assertIsNotNone(self.user.review_request_email_sent_at)


if __name__ == "__main__":
    unittest.main()
