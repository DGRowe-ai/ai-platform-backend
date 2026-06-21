import re

PHONE_DIGITS_MIN = 10
PHONE_DIGITS_MAX = 15


class InvalidBusinessPhoneError(ValueError):
    pass


def validate_business_phone(value: str) -> None:
    digits = re.sub(r"\D", "", (value or "").strip())
    if len(digits) < PHONE_DIGITS_MIN or len(digits) > PHONE_DIGITS_MAX:
        raise InvalidBusinessPhoneError(
            "Enter a valid phone number with 10 to 15 digits."
        )


def normalize_business_phone(value: str) -> str:
    stripped = (value or "").strip()
    if not stripped:
        raise InvalidBusinessPhoneError("Business phone number is required.")

    validate_business_phone(stripped)
    digits = re.sub(r"\D", "", stripped)

    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"

    if len(digits) == 11 and digits.startswith("1"):
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:11]}"

    return f"+{digits}"


def is_reasonable_phone_input(value: str) -> bool:
    try:
        validate_business_phone(value)
        return True
    except InvalidBusinessPhoneError:
        return False
