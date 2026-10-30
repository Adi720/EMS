"""Phone number parsing and normalisation (default region: India)."""

import re
from dataclasses import dataclass

import phonenumbers
from django.conf import settings

SPLIT_RE = re.compile(r"\s*(?:/|,|;|\n|\r|\bor\b)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedPhone:
    raw: str
    e164: str | None  # None when the number is not valid

    @property
    def is_valid(self):
        return self.e164 is not None


def raw_phone_text(value):
    """Turn a spreadsheet cell into text without float/scientific-notation damage."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value).strip()


def normalize_phone(text, region=None):
    """Return the E.164 form of ``text`` or None if it is not a valid number."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        number = phonenumbers.parse(text, region or settings.PHONE_DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def split_phones(text):
    """Split a cell that may hold several numbers ("98.../97...") into parts."""
    return [part for part in SPLIT_RE.split(text or "") if part.strip()]


def parse_phone_cell(value):
    """Parse a raw cell into a list of ParsedPhone (usually one)."""
    text = raw_phone_text(value)
    return [ParsedPhone(raw=part.strip(), e164=normalize_phone(part)) for part in split_phones(text)]


def phone_digits(text):
    return re.sub(r"\D", "", text or "")


def display_phone(e164):
    """Readable national format for display, e.g. 098765 43210 → 98765 43210."""
    if not e164:
        return ""
    try:
        number = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException:
        return e164
    if number.country_code == phonenumbers.country_code_for_region(settings.PHONE_DEFAULT_REGION):
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL).lstrip("0")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
