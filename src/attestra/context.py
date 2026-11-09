"""Authenticated request identity passed to application handlers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Identity and correlation fields supplied or verified for one request."""

    tenant_id: str
    user_id: str
    request_id: str
    client_id: str
