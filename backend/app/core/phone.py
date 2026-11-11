import re
import unicodedata

import phonenumbers


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: str, default_region: str = "IN") -> str:
    """Return E.164 (+919876543210). Indian 10-digit mobiles are accepted without a country code."""
    if not raw or not raw.strip():
        raise InvalidPhone("Phone number is required.")
    cleaned = re.sub(r"[^\d+]", "", raw.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    try:
        num = phonenumbers.parse(cleaned, default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone("Enter a valid mobile number.") from exc
    if not phonenumbers.is_valid_number(num):
        raise InvalidPhone("Enter a valid mobile number.")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def wa_id(e164: str) -> str:
    """WhatsApp IDs are E.164 digits without '+'."""
    return e164.lstrip("+")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).strip().lower()
    text = re.sub(r"^(mr|mrs|ms|miss|dr|master|thiru|tmt|selvi)\.?\s+", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def mask_phone(e164: str) -> str:
    return e164[:-6] + "••••" + e164[-2:] if len(e164) > 8 else "••••"
