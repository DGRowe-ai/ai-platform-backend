import unittest

from twilio_realtime_bridge import (
    build_voice_twiml,
    get_media_stream_wss_url,
    _openai_realtime_uri,
    _resolve_realtime_model,
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

    def test_deprecated_preview_model_maps_to_ga(self):
        self.assertEqual(
            _resolve_realtime_model("gpt-4o-mini-realtime-preview"),
            "gpt-realtime-mini",
        )
        self.assertEqual(
            _resolve_realtime_model("gpt-4o-realtime-preview-2024-12-17"),
            "gpt-realtime",
        )

    def test_realtime_uri_remaps_deprecated_env_model(self):
        import os

        os.environ["REALTIME_MODEL"] = "gpt-4o-mini-realtime-preview"
        try:
            uri = _openai_realtime_uri()
            self.assertIn("model=gpt-realtime-mini", uri)
        finally:
            os.environ.pop("REALTIME_MODEL", None)


if __name__ == "__main__":
    unittest.main()
