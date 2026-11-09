"""Redact detected PII in text and nested JSON values."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from presidio_analyzer import PatternRecognizer

from attestra.redaction.recognizers import build_pattern_recognizers
from attestra.redaction.token_map import RedactionMap

_ENTITY_TYPE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Return a redacted value and its per-run in-memory token map."""

    value: Any
    token_map: RedactionMap


class Redactor:
    """Redact common patterns and values supplied by the caller."""

    def __init__(self, recognizers: Sequence[PatternRecognizer] | None = None) -> None:
        self._recognizers = tuple(recognizers or build_pattern_recognizers())

    def redact(
        self,
        value: str | dict[str, Any] | list[Any],
        caller_values: Mapping[str, Sequence[str]] | None = None,
    ) -> RedactionResult:
        """Redact text or string values in nested JSON without changing the input."""
        replacements: dict[str, str] = {}
        value_tokens: dict[tuple[str, str], str] = {}
        next_token_by_type: dict[str, int] = {}
        reserved = {
            token
            for text in _all_strings(value)
            for token in re.findall(r"\[[A-Z][A-Z0-9_]*_\d+\]", text)
        }

        def replace_text(text: str) -> str:
            candidates = self._find_candidates(text, caller_values or {})
            pieces: list[str] = []
            cursor = 0
            for candidate in _resolve_overlaps(candidates):
                entity_type, start, end = candidate
                original = text[start:end]
                key = (entity_type, original.casefold())
                token = value_tokens.get(key)
                if token is None:
                    index = next_token_by_type.get(entity_type, 0) + 1
                    token = f"[{entity_type}_{index}]"
                    while token in reserved or token in replacements:
                        index += 1
                        token = f"[{entity_type}_{index}]"
                    next_token_by_type[entity_type] = index
                    value_tokens[key] = token
                    replacements[token] = original
                pieces.extend((text[cursor:start], token))
                cursor = end
            pieces.append(text[cursor:])
            return "".join(pieces)

        redacted_value = _map_strings(value, replace_text)
        return RedactionResult(redacted_value, RedactionMap(replacements))

    def restore(self, value: str | dict[str, Any] | list[Any], token_map: RedactionMap) -> Any:
        """Restore tokens in text or nested JSON using the matching per-run map."""
        replacements = sorted(token_map.values.items(), key=lambda item: len(item[0]), reverse=True)

        def restore_text(text: str) -> str:
            for token, original in replacements:
                text = text.replace(token, original)
            return text

        return _map_strings(value, restore_text)

    def _find_candidates(
        self,
        text: str,
        caller_values: Mapping[str, Sequence[str]],
    ) -> list[tuple[str, int, int]]:
        candidates: list[tuple[str, int, int]] = []
        for recognizer in self._recognizers:
            entity_type = recognizer.supported_entities[0]
            for result in recognizer.analyze(text, [entity_type]):
                start, end = result.start, result.end
                if entity_type == "ACCOUNT_NUMBER":
                    number = re.search(r"\d{6,18}$", text[start:end])
                    if number is None:
                        continue
                    start += number.start()
                candidates.append((entity_type, start, end))
        for entity_type, values in caller_values.items():
            if not _ENTITY_TYPE.fullmatch(entity_type):
                raise ValueError("Caller value entity types must be uppercase identifiers")
            for value in values:
                if not value:
                    continue
                candidates.extend(_find_normalized_matches(text, entity_type, value))
        return candidates


def _resolve_overlaps(
    candidates: Sequence[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    ordered = sorted(candidates, key=lambda item: (item[1], -(item[2] - item[1])))
    resolved: list[tuple[str, int, int]] = []
    last_end = -1
    for candidate in ordered:
        if candidate[1] >= last_end:
            resolved.append(candidate)
            last_end = candidate[2]
    return resolved


def _find_normalized_matches(text: str, entity_type: str, value: str) -> list[tuple[str, int, int]]:
    normalized_value = _normalize_with_positions(value)[0]
    if not normalized_value:
        return []
    normalized_text, positions = _normalize_with_positions(text)
    matches: list[tuple[str, int, int]] = []
    start = 0
    while (index := normalized_text.find(normalized_value, start)) >= 0:
        stop = index + len(normalized_value)
        if (index == 0 or not text[positions[index] - 1].isalnum()) and (
            stop == len(positions) or not text[positions[stop - 1] + 1].isalnum()
        ):
            matches.append((entity_type, positions[index], positions[stop - 1] + 1))
        start = index + 1
    return matches


def _normalize_with_positions(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(value):
        if character.isalnum():
            folded = character.casefold()
            normalized.extend(folded)
            positions.extend([index] * len(folded))
    return "".join(normalized), positions


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [item for nested in value.values() for item in _all_strings(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _all_strings(nested)]
    return []


def _map_strings(value: Any, operation: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return operation(value)
    if isinstance(value, dict):
        return {key: _map_strings(nested, operation) for key, nested in value.items()}
    if isinstance(value, list):
        return [_map_strings(nested, operation) for nested in value]
    return value
