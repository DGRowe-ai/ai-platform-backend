import json
import unittest

from widget_settings_utils import (
    DEFAULT_WIDGET_SETTINGS,
    WidgetSettingsPayload,
    merge_with_defaults,
    parse_settings_json,
    serialize_public_settings,
)


class WidgetSettingsUtilsTests(unittest.TestCase):
    def test_defaults_merge(self):
        merged = merge_with_defaults({"primaryColor": "#112233"})
        self.assertEqual(merged["primaryColor"], "#112233")
        self.assertEqual(merged["position"], DEFAULT_WIDGET_SETTINGS["position"])

    def test_validate_payload(self):
        payload = WidgetSettingsPayload.model_validate(
            {
                "primaryColor": "#4F46E5",
                "secondaryColor": "#FFFFFF",
                "chatBubbleColor": "#4F46E5",
                "textColor": "#000000",
                "welcomeMessage": "Hello!",
                "position": "bottom-left",
                "showAvatar": True,
                "widgetShape": "circle",
                "fontFamily": "Inter",
                "customCSS": ".chat { color: red; }",
                "enableShadow": False,
                "enableTypingAnimation": True,
            }
        )
        self.assertEqual(payload.position, "bottom-left")

    def test_reject_invalid_color(self):
        with self.assertRaises(Exception):
            WidgetSettingsPayload.model_validate(
                {**DEFAULT_WIDGET_SETTINGS, "primaryColor": "red"}
            )

    def test_public_serialization(self):
        public = serialize_public_settings(DEFAULT_WIDGET_SETTINGS)
        self.assertIn("welcomeMessage", public)
        self.assertNotIn("business_id", public)

    def test_parse_invalid_json(self):
        parsed = parse_settings_json("{not-json")
        self.assertEqual(parsed["primaryColor"], DEFAULT_WIDGET_SETTINGS["primaryColor"])


if __name__ == "__main__":
    unittest.main()
