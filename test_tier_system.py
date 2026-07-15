"""Unit tests for the new tier system and founders coupon."""

import unittest

from plan_utils import (
    product_type_from_tier,
    normalize_checkout_plan,
    tier_allows_multi_location,
    tier_allows_call_forwarding,
    tier_allows_basic_appointments,
    tier_allows_appointment_notifications,
    tier_allows_appointment_followups,
    get_tier_price_cents,
)
from utils.coupons import (
    validate_coupon,
    get_checkout_unit_amount,
    get_discount_amount,
)


class TierSystemTests(unittest.TestCase):
    def test_normalize_legacy_plans(self):
        self.assertEqual(normalize_checkout_plan("voicebot"), "starter")
        self.assertEqual(normalize_checkout_plan("duo"), "duo_starter")
        self.assertEqual(normalize_checkout_plan("premium"), "premium")

    def test_product_type_mapping(self):
        self.assertEqual(product_type_from_tier("chatbot"), "chatbot")
        self.assertEqual(product_type_from_tier("pro"), "voicebot")
        self.assertEqual(product_type_from_tier("duo_premium"), "duo")

    def test_prices_have_no_nines(self):
        expected = {
            "chatbot": 4000,
            "starter": 10000,
            "pro": 15000,
            "premium": 20000,
            "duo_starter": 13000,
            "duo_pro": 17000,
            "duo_premium": 22000,
        }
        for tier, cents in expected.items():
            self.assertEqual(get_tier_price_cents(tier), cents)

    def test_feature_gates(self):
        self.assertFalse(tier_allows_multi_location("starter"))
        self.assertFalse(tier_allows_multi_location("pro"))
        self.assertTrue(tier_allows_multi_location("premium"))
        self.assertTrue(tier_allows_multi_location("duo_premium"))
        self.assertFalse(tier_allows_call_forwarding("starter"))
        self.assertTrue(tier_allows_call_forwarding("pro"))
        self.assertTrue(tier_allows_call_forwarding("duo_pro"))

    def test_appointment_feature_gates(self):
        self.assertTrue(tier_allows_basic_appointments("starter"))
        self.assertTrue(tier_allows_basic_appointments("duo_starter"))
        self.assertFalse(tier_allows_appointment_notifications("starter"))
        self.assertFalse(tier_allows_appointment_notifications("duo_starter"))
        self.assertFalse(tier_allows_appointment_followups("starter"))
        self.assertTrue(tier_allows_appointment_notifications("pro"))
        self.assertTrue(tier_allows_appointment_followups("pro"))
        self.assertTrue(tier_allows_appointment_notifications("duo_pro"))
        self.assertTrue(tier_allows_appointment_followups("duo_premium"))


class FoundersCouponTests(unittest.TestCase):
    def test_applies_to_voice_and_duo_only(self):
        for tier in ("starter", "pro", "premium", "duo_starter", "duo_pro", "duo_premium"):
            self.assertTrue(validate_coupon("FOUNDERS10", tier), tier)
            self.assertEqual(get_discount_amount("FOUNDERS10", tier), 1000)
            self.assertEqual(
                get_checkout_unit_amount(tier, "FOUNDERS10"),
                get_tier_price_cents(tier) - 1000,
            )

        self.assertFalse(validate_coupon("FOUNDERS10", "chatbot"))
        self.assertEqual(get_checkout_unit_amount("chatbot", "FOUNDERS10"), 4000)

    def test_deprecated_chatbot_coupons_rejected(self):
        self.assertFalse(validate_coupon("CHATBOT10", "chatbot"))
        self.assertFalse(validate_coupon("FOREVER10CHATBOT", "starter"))


if __name__ == "__main__":
    unittest.main()
