"""Tests for PII recognition, tokenization, and restoration."""

import pytest

from attestra.redaction import Redactor


@pytest.mark.parametrize(
    ("entity", "text", "expected"),
    [
        (
            "EMAIL_ADDRESS",
            "Contact Ada at ada@example.com today",
            "Contact Ada at [EMAIL_ADDRESS_1] today",
        ),
        ("PHONE_NUMBER", "Call +1 212-555-0123 for help", "Call [PHONE_NUMBER_1] for help"),
        (
            "CREDIT_CARD",
            "Card 4111 1111 1111 1111",
            "Card [CREDIT_CARD_1]",
        ),
        (
            "IBAN",
            "IBAN GB82 WEST 1234 5698 7654 32",
            "IBAN [IBAN_1]",
        ),
        (
            "ACCOUNT_NUMBER",
            "Account number: 123456789",
            "Account number: [ACCOUNT_NUMBER_1]",
        ),
    ],
)
def test_redacts_common_patterns(entity: str, text: str, expected: str) -> None:
    result = Redactor().redact(text)

    assert result.value == expected
    assert next(iter(result.token_map.values))
    assert next(iter(result.token_map.values.values()))


@pytest.mark.parametrize(
    "text",
    [
        "Card 4111 1111 1111 1112",
        "IBAN GB82 WEST 1234 5698 7654 33",
        "Reference 123456789 is not labeled as an account",
        "Date 2024-01-31 is not assumed to be a date of birth",
    ],
)
def test_does_not_redact_invalid_or_ambiguous_values(text: str) -> None:
    assert Redactor().redact(text).value == text


def test_redacts_caller_values_exactly_and_after_normalization() -> None:
    value = "DOB: 1990-02-03; customer: Mary Jane Smith; id: AB-12345"
    result = Redactor().redact(
        value,
        {
            "DATE_OF_BIRTH": ["1990-02-03"],
            "PERSON": ["Mary Jane Smith"],
            "NATIONAL_ID": ["AB12345"],
        },
    )

    assert result.value == ("DOB: [DATE_OF_BIRTH_1]; customer: [PERSON_1]; id: [NATIONAL_ID_1]")
    assert Redactor().restore(result.value, result.token_map) == value


def test_redacts_and_restores_nested_json_without_mutating_input() -> None:
    value = {
        "customer": {"email": "ada@example.com"},
        "notes": ["call +1 212-555-0123", 4, None],
    }

    result = Redactor().redact(value)

    assert result.value == {
        "customer": {"email": "[EMAIL_ADDRESS_1]"},
        "notes": ["call [PHONE_NUMBER_1]", 4, None],
    }
    assert value["customer"]["email"] == "ada@example.com"
    assert Redactor().restore(result.value, result.token_map) == value


def test_reuses_tokens_for_repeated_values_and_avoids_input_collisions() -> None:
    result = Redactor().redact("[EMAIL_ADDRESS_1] ada@example.com and ada@example.com")

    assert result.value == "[EMAIL_ADDRESS_1] [EMAIL_ADDRESS_2] and [EMAIL_ADDRESS_2]"
    assert Redactor().restore(result.value, result.token_map) == (
        "[EMAIL_ADDRESS_1] ada@example.com and ada@example.com"
    )


def test_caller_entity_type_must_be_safe_identifier() -> None:
    with pytest.raises(ValueError, match="uppercase identifiers"):
        Redactor().redact("value", {"personal data": ["value"]})
