import os
import unittest
from unittest import mock

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SMTP_SERVER", "smtp.example.com")
os.environ.setdefault("SMTP_PORT", "587")
os.environ.setdefault("SMTP_USER", "smtp-user")
os.environ.setdefault("SMTP_PASSWORD", "smtp-password")
os.environ.setdefault("VERIFIED_SENDER", "verified@example.com")
os.environ.setdefault("PASSWORD_RESET_SENDER", "support@roweai.ca")

from email_utils import (
    CLIENT_SERVICE_AGREEMENT_FILENAME,
    _get_client_service_agreement_bytes,
    send_duo_welcome_email,
    send_referred_user_welcome_email,
    send_voicebot_welcome_email,
    send_welcome_email_with_referral,
)


class WelcomeEmailAttachmentTests(unittest.TestCase):
    def test_client_service_agreement_asset_exists(self):
        pdf_bytes = _get_client_service_agreement_bytes()
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 100)

    def _assert_welcome_sends_agreement(self, send_fn, **kwargs):
        captured = {}

        class FakeSMTP:
            def __init__(self, host, port):
                captured["host"] = host
                captured["port"] = port

            def starttls(self):
                return None

            def login(self, user, password):
                captured["login"] = (user, password)

            def sendmail(self, sender, to_email, message):
                captured["sender"] = sender
                captured["to_email"] = to_email
                captured["message"] = message

            def quit(self):
                return None

        with mock.patch("email_utils.smtplib.SMTP", FakeSMTP):
            send_fn(**kwargs)

        self.assertIn(CLIENT_SERVICE_AGREEMENT_FILENAME, captured["message"])
        self.assertIn("Client Service Agreement", captured["message"])
        self.assertIn("application/pdf", captured["message"])
        self.assertEqual(captured["to_email"], kwargs["to_email"])
        self.assertEqual(captured["sender"], "support@roweai.ca")

    def test_chatbot_welcome_attaches_agreement(self):
        self._assert_welcome_sends_agreement(
            send_welcome_email_with_referral,
            to_email="client@example.com",
            business_name="Test Shop",
            chatbot_link="https://example.com/bot",
            dashboard_link="https://example.com/dashboard",
            embed_code="<script></script>",
            referral_link="https://example.com/r/abc",
        )

    def test_voicebot_welcome_attaches_agreement(self):
        self._assert_welcome_sends_agreement(
            send_voicebot_welcome_email,
            to_email="client@example.com",
            client_name="Test Shop",
        )

    def test_duo_welcome_attaches_agreement(self):
        self._assert_welcome_sends_agreement(
            send_duo_welcome_email,
            to_email="client@example.com",
            client_name="Test Shop",
        )

    def test_referred_welcome_attaches_agreement(self):
        self._assert_welcome_sends_agreement(
            send_referred_user_welcome_email,
            to_email="client@example.com",
            business_name="Test Shop",
            referrer_name="Referrer Co",
        )


if __name__ == "__main__":
    unittest.main()
