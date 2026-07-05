import unittest

from models import Business, BusinessSettings
from voice_settings_utils import build_voice_realtime_instructions, serialize_voice_settings


class VoiceSettingsInstructionTests(unittest.TestCase):
    def test_instructions_enforce_exact_business_name(self):
        settings = BusinessSettings(
            business_id=1,
            voice_business_name="Rowe AI",
            voice_custom_instructions="Hours: Mon-Fri 9am-5pm. Service area: Guelph area and worldwide.",
            voice_tone="professional",
        )
        instructions = build_voice_realtime_instructions(
            settings,
            business_name="Rowe",
        )
        self.assertIn('exactly "Rowe AI"', instructions)
        self.assertIn("Speak only in English", instructions)
        self.assertIn("Guelph area and worldwide", instructions)
        self.assertIn("BUSINESS FACTS", instructions)

    def test_serialize_prefers_voice_business_name(self):
        settings = BusinessSettings(
            business_id=1,
            voice_business_name="Rowe AI",
        )
        business = Business(id=1, name="Rowe", folder_name="rowe", owner_id=1)
        payload = serialize_voice_settings(settings, business)
        self.assertEqual(payload["businessName"], "Rowe AI")


if __name__ == "__main__":
    unittest.main()
