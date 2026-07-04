import unittest

from twilio_realtime_bridge import (
    build_voice_twiml,
    get_media_stream_wss_url,
    _openai_realtime_uri,
)


class TwilioRealtimeBridgeTests(unittest.TestCase):
    def test_media_stream_url_from_https(self):
        import os

        os.environ["BACKEND_PUBLIC_URL"] = "https://ai-platform-backend-ulqs.onrender.com"
        self.assertEqual(
            get_media_stream_wss_url(),
            "wss://ai-platform-backend-ulqs.onrender.com/media",
        )

    def test_voice_twiml_uses_connect_stream(self):
        twiml = build_voice_twiml("wss://example.com/media")
        self.assertIn("<Connect>", twiml)
        self.assertIn("<Stream url=\"wss://example.com/media\"", twiml)
        self.assertNotIn("<Pause", twiml)

    def test_realtime_uri_uses_ga_model(self):
        import os

        os.environ.pop("REALTIME_MODEL", None)
        uri = _openai_realtime_uri()
        self.assertIn("model=gpt-realtime", uri)


if __name__ == "__main__":
    unittest.main()
