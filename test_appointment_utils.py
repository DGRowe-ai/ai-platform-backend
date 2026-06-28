import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from appointment_utils import (
    APPOINTMENT_KNOWLEDGE_LINE,
    normalize_appointment_datetime,
    validate_contact,
    validate_appointment_payload,
)


class AppointmentUtilsTests(unittest.TestCase):
    def test_validate_contact_email(self):
        self.assertEqual(validate_contact("User@Example.com"), "user@example.com")

    def test_validate_contact_phone(self):
        self.assertEqual(validate_contact("(416) 555-1234"), "(416) 555-1234")

    def test_normalize_future_datetime(self):
        future_date = (datetime.now(ZoneInfo("UTC")) + timedelta(days=2)).date()
        date_text, time_text, normalized = normalize_appointment_datetime(
            future_date.isoformat(),
            "2:30 PM",
            "UTC",
        )
        self.assertEqual(date_text, future_date.isoformat())
        self.assertEqual(time_text, "14:30")
        self.assertIn("202", normalized)

    def test_validate_payload_requires_service(self):
        future_date = (datetime.now(ZoneInfo("UTC")) + timedelta(days=3)).date()
        with self.assertRaises(Exception):
            validate_appointment_payload(
                {
                    "customer_name": "Jane Doe",
                    "customer_contact": "jane@example.com",
                    "requested_date": future_date.isoformat(),
                    "requested_time": "10:00",
                    "service": "",
                },
                "America/Toronto",
            )

    def test_knowledge_line_present(self):
        self.assertIn("appointment", APPOINTMENT_KNOWLEDGE_LINE.lower())


if __name__ == "__main__":
    unittest.main()
