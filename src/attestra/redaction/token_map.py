"""Per-call reversible mappings for redaction tokens."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RedactionMap:
    """Hold sensitive values in memory for restoring one redaction result."""

    values: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
