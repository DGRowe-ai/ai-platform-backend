import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from payment_log_utils import (
    append_payment_log,
    business_name_to_payment_folder_name,
    get_payment_log_metadata,
    initialize_payment_log,
    payment_description_from_invoice,
    read_payment_log_entries,
)


class PaymentLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["PAYMENTS_LOG_DIR"] = self.temp_dir.name
        import payment_log_utils

        payment_log_utils.PAYMENTS_ROOT = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("PAYMENTS_LOG_DIR", None)

    def test_business_name_to_payment_folder_name(self):
        self.assertEqual(
            business_name_to_payment_folder_name("Acme Coffee Shop"),
            "acme-coffee-shop",
        )
        self.assertEqual(
            business_name_to_payment_folder_name("Rowe-AI Website"),
            "rowe-ai-website",
        )

    def test_initialize_payment_log_creates_folder_and_file(self):
        log_path = initialize_payment_log("Acme Coffee Shop")
        self.assertTrue(log_path.exists())
        self.assertEqual(log_path.name, "payments.log")
        self.assertEqual(log_path.parent.name, "acme-coffee-shop")

    def test_append_payment_log_writes_expected_line(self):
        initialize_payment_log("Acme Coffee Shop")
        append_payment_log(
            "Acme Coffee Shop",
            amount_cents=2999,
            invoice_id="in_test123",
            description="Monthly subscription",
            paid_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        )

        log_path = Path(self.temp_dir.name) / "acme-coffee-shop" / "payments.log"
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("2026-06-19 | $29.99 | in_test123 | Monthly subscription", content)

    def test_payment_description_from_invoice(self):
        description = payment_description_from_invoice(
            {
                "billing_reason": "subscription_cycle",
                "lines": {"data": [{"description": "RoweAI Pro Plan"}]},
            }
        )
        self.assertEqual(description, "RoweAI Pro Plan")

        fallback = payment_description_from_invoice({"billing_reason": "subscription_cycle"})
        self.assertEqual(fallback, "Monthly subscription")

    def test_read_payment_log_entries(self):
        initialize_payment_log("Acme Coffee Shop")
        append_payment_log(
            "Acme Coffee Shop",
            amount_cents=2999,
            invoice_id="in_test123",
            description="Monthly subscription",
            paid_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        )

        entries = read_payment_log_entries("Acme Coffee Shop")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["invoice_id"], "in_test123")
        self.assertEqual(entries[0]["amount"], "$29.99")

        metadata = get_payment_log_metadata("Acme Coffee Shop")
        self.assertEqual(metadata["entry_count"], 1)
        self.assertEqual(metadata["last_payment_date"], "2026-06-19")


if __name__ == "__main__":
    unittest.main()
