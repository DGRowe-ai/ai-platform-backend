import unittest

from phone_utils import (
    InvalidBusinessPhoneError,
    is_reasonable_phone_input,
    normalize_business_phone,
    validate_business_phone,
)


class PhoneUtilsTests(unittest.TestCase):
    def test_normalize_ten_digit_na_phone(self):
        self.assertEqual(
            normalize_business_phone("5551234567"),
            "(555) 123-4567",
        )
        self.assertEqual(
            normalize_business_phone("(555) 123-4567"),
            "(555) 123-4567",
        )

    def test_normalize_eleven_digit_na_phone(self):
        self.assertEqual(
            normalize_business_phone("1-555-123-4567"),
            "+1 (555) 123-4567",
        )

    def test_reject_short_phone(self):
        with self.assertRaises(InvalidBusinessPhoneError):
            validate_business_phone("12345")

    def test_reject_empty_phone(self):
        with self.assertRaises(InvalidBusinessPhoneError):
            normalize_business_phone("")

    def test_is_reasonable_phone_input(self):
        self.assertTrue(is_reasonable_phone_input("416-555-1234"))
        self.assertFalse(is_reasonable_phone_input("abc"))


if __name__ == "__main__":
    unittest.main()
