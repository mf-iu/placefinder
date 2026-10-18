"""Errors as problem details (RFC 9457, media type application/problem+json).

Every error of the API has the same format: the own exception Problem, the
HTTP errors of FastAPI and Starlette (404 for unknown paths, 405 ...) and
invalid parameters (422).
"""

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

# base URI of the problem types; .test is reserved for tests (RFC 2606)
PROBLEMS = "https://placefinder.test/problems"
MEDIA_TYPE = "application/problem+json"


class ProblemDetails(BaseModel):
    """Body of an error response, for the OpenAPI description."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


@dataclass
class Problem(Exception):
    """An error of the API: raise Problem(404, "place-not-found", ...)."""

    status: int
    type: str
    title: str
    detail: str
    extra: dict[str, Any] | None = None  # own fields, e.g. {"parameter": "bbox"}


def problem_response(
    request: Request,
    status: int,
    type_: str,
    title: str,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the response; type_ is a name below PROBLEMS or "about:blank"."""
    body: dict[str, Any] = {
        "type": type_ if type_ == "about:blank" else f"{PROBLEMS}/{type_}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    body.update(extra or {})
    return JSONResponse(
        {key: value for key, value in body.items() if value is not None},
        status_code=status,
        media_type=MEDIA_TYPE,
        headers=headers,
    )


def add_problem_handlers(app: FastAPI) -> None:
    """Register the handlers that turn all errors into problem details."""

    @app.exception_handler(Problem)
    async def own_problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(request, exc.status, exc.type, exc.title, exc.detail, exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # e.g. 404 for an unknown path, 405 with the header Allow
        phrase = HTTPStatus(exc.status_code).phrase
        detail = exc.detail if exc.detail != phrase else None
        return problem_response(
            request, exc.status_code, "about:blank", phrase, detail, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_parameters(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            request,
            422,
            "invalid-parameters",
            "Invalid parameters",
            "One or more parameters are invalid",
            {"errors": jsonable_encoder(exc.errors(), exclude={"url", "input", "ctx"})},
        )


def documented(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI description of error responses with problem details."""
    schema = ProblemDetails.model_json_schema()
    return {
        status: {
            "description": HTTPStatus(status).phrase,
            "content": {MEDIA_TYPE: {"schema": schema}},
        }
        for status in statuses
    }
