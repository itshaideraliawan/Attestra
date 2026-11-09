"""Presidio pattern recognizers for common sensitive values."""

import re

from presidio_analyzer import Pattern, PatternRecognizer

_PHONE_PATTERN = (
    r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{3})"
    r"(?:[ .-]\d{3,4}){2}(?![\w .-]?\d)"
)


class CreditCardRecognizer(PatternRecognizer):
    """Recognize card numbers that pass the Luhn checksum."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="CREDIT_CARD",
            name="Attestra credit card recognizer",
            patterns=[
                Pattern(
                    "credit card number",
                    r"(?<!\w)(?:\d[ -]?){13,19}(?!\w)",
                    0.5,
                )
            ],
        )

    def validate_result(self, pattern_text: str) -> bool:
        digits = re.sub(r"\D", "", pattern_text)
        if not 13 <= len(digits) <= 19:
            return False
        checksum = 0
        for index, digit in enumerate(reversed(digits)):
            value = int(digit)
            if index % 2:
                value *= 2
                if value > 9:
                    value -= 9
            checksum += value
        return checksum % 10 == 0


class IbanRecognizer(PatternRecognizer):
    """Recognize IBAN-shaped values that pass the MOD-97 check."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IBAN",
            name="Attestra IBAN recognizer",
            patterns=[
                Pattern(
                    "IBAN format",
                    r"(?<![A-Z0-9])(?:[A-Z]{2}\d{2})(?:[ ]?[A-Z0-9]){11,30}(?![A-Z0-9])",
                    0.5,
                )
            ],
        )

    def validate_result(self, pattern_text: str) -> bool:
        compact = re.sub(r"\s", "", pattern_text).upper()
        if not 15 <= len(compact) <= 34 or not compact[:2].isalpha() or not compact[2:4].isdigit():
            return False
        rearranged = compact[4:] + compact[:4]
        remainder = 0
        for character in rearranged:
            digits = character if character.isdigit() else str(ord(character) - 55)
            for digit in digits:
                remainder = (remainder * 10 + int(digit)) % 97
        return remainder == 1


def build_pattern_recognizers() -> tuple[PatternRecognizer, ...]:
    """Create recognizers with conservative patterns for common PII."""
    return (
        PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            name="Attestra email recognizer",
            patterns=[
                Pattern(
                    "email",
                    r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
                    0.8,
                )
            ],
        ),
        PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            name="Attestra phone recognizer",
            patterns=[
                Pattern(
                    "phone",
                    _PHONE_PATTERN,
                    0.5,
                )
            ],
        ),
        CreditCardRecognizer(),
        IbanRecognizer(),
        PatternRecognizer(
            supported_entity="ACCOUNT_NUMBER",
            name="Attestra account number recognizer",
            patterns=[
                Pattern(
                    "account number",
                    r"(?i)(?:\baccount(?:\s+(?:number|no\.?))?|\bacct\.?|\ba/c)\s*[:#-]?\s*\d{6,18}(?!\w)",
                    0.35,
                )
            ],
        ),
    )
