import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from trial_protection_utils import (
    check_trial_eligibility,
    normalize_device_fingerprint,
    phone_digits_for_trial,
    record_trial_enrollment,
)


class TrialProtectionUtilsTests(unittest.TestCase):
    def test_phone_digits_for_trial(self):
        self.assertEqual(phone_digits_for_trial("(416) 555-1234"), "4165551234")

    def test_normalize_device_fingerprint(self):
        value = "a" * 64
        self.assertEqual(normalize_device_fingerprint(value), value)
        self.assertIsNone(normalize_device_fingerprint("not-a-hash"))

    def test_check_trial_eligibility_blocks_used_email(self):
        db = MagicMock()
        existing = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        result = check_trial_eligibility(db, email="user@example.com")

        self.assertFalse(result.eligible)
        self.assertIn("email", result.reason.lower())

    def test_check_trial_eligibility_allows_clean_signup(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.count.return_value = 0

        result = check_trial_eligibility(
            db,
            email="new-user@example.com",
            phone="(416) 555-9999",
            ip_address="203.0.113.10",
        )

        self.assertTrue(result.eligible)

    def test_record_trial_enrollment_upserts_existing(self):
        db = MagicMock()
        existing = MagicMock()
        existing.phone = None
        existing.stripe_customer_id = "cus_123"
        existing.card_fingerprint = None
        existing.device_fingerprint = None
        existing.ip_address = None
        existing.stripe_subscription_id = None

        db.query.return_value.filter.return_value.first.return_value = existing

        record = record_trial_enrollment(
            db,
            email="user@example.com",
            phone="(416) 555-1234",
            stripe_customer_id="cus_123",
        )

        self.assertEqual(record, existing)
        self.assertEqual(existing.phone, "4165551234")
        db.add.assert_called_with(existing)
        db.commit.assert_called()


if __name__ == "__main__":
    unittest.main()
