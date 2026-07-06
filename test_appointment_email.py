import unittest
from unittest.mock import patch

from utils.appointment_email import send_appointment_email


class AppointmentEmailTests(unittest.TestCase):
    @patch("utils.appointment_email.send_email")
    def test_send_appointment_email_uses_specified_subject_and_fields(self, mock_send):
        send_appointment_email(
            "owner@example.com",
            {
                "customerName": "Jane Doe",
                "customerPhone": "416-555-1234",
                "requestedDate": "2026-07-15",
                "requestedTime": "14:30",
                "service": "Consultation",
                "notes": "First visit",
            },
        )

        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["to_email"], "owner@example.com")
        self.assertEqual(kwargs["subject"], "New Appointment Request")
        self.assertIn("Jane Doe", kwargs["body"])
        self.assertIn("416-555-1234", kwargs["body"])
        self.assertIn("Consultation", kwargs["body"])
        self.assertIn("First visit", kwargs["body"])
        self.assertIn("confirm or reject", kwargs["body"].lower())

    @patch("utils.appointment_email.send_email")
    def test_send_appointment_email_skips_blank_recipient(self, mock_send):
        send_appointment_email("", {"customerName": "Jane Doe"})
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
