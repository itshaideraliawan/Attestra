"""RFC 9457 problem details for HTTP errors."""

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse


class Problem(BaseModel):
    """A safe, machine-readable HTTP error response."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    request_id: str | None = None


class ProblemException(Exception):
    """An expected request failure with an HTTP status and safe detail."""

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.headers = headers


def problem_response(
    request: Request,
    status_code: int,
    title: str,
    detail: str,
    headers: Mapping[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a problem response without echoing request values."""
    request_id = getattr(request.state, "request_id", None)
    problem = Problem(
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        request_id=request_id,
        **(extensions or {}),
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
        headers=headers,
    )
