"""PlaceFinder API: search places of GeoNames, in memory or in PostGIS.

Version 1 under /v1 (from session 5): GeoJSON, filters, cursor pagination,
ETags and errors as problem details. The unversioned endpoints of stage v0
(/places) remain for a while and are marked as deprecated.

With DATABASE_URL set, the places come from PostgreSQL with PostGIS (from
session 6, db.py); otherwise PlaceFinder loads the GeoNames file DATA_FILE
into memory at startup (places.py).

Start for development:  uv run fastapi dev src/placefinder/main.py
Start for production:   uvicorn placefinder.main:app --host 0.0.0.0 --port 8000
Settings: DATABASE_URL (PostgreSQL connection string), DATA_FILE (GeoNames text
file), LOG_LEVEL (default info), CORS_ORIGINS (origins of web pages that may
call the API)
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import OperationalError

from placefinder.api import create_router, repository
from placefinder.db import PostgisRepository, describe
from placefinder.places import PlaceRepository
from placefinder.problems import Problem, add_problem_handlers, documented, problem_response
from placefinder.repository import Place, Repository, SearchQuery

# default data file, relative to the working directory; override with DATA_FILE
DEFAULT_DATA_FILE = "data/cities15000.txt"
ATTRIBUTION = "Place data: GeoNames (https://www.geonames.org), CC BY 4.0"
# the map of frontend/index.html, served with python3 -m http.server 5173
DEFAULT_CORS_ORIGINS = "http://localhost:5173"
# v0 is deprecated since 01.10.2026 (RFC 9745) and ends on 01.01.2027 (RFC 8594)
V0_HEADERS = {
    "Deprecation": "@1790812800",
    "Sunset": "Fri, 01 Jan 2027 00:00:00 GMT",
    "Link": '</v1/places>; rel="successor-version"',
}

# uvicorn configures this logger, so its messages appear in the server output
logger = logging.getLogger("uvicorn.error")
# level from the environment, e.g. a Kubernetes ConfigMap: debug, info, warning, error
logger.setLevel(os.environ.get("LOG_LEVEL", "info").upper())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Choose the place store once at startup, before the first request:
    PostGIS with DATABASE_URL, otherwise the GeoNames file in memory."""
    if url := os.environ.get("DATABASE_URL"):
        db = PostgisRepository(url)
        db.open()  # fails early if the database or the table places is missing
        logger.info("Using PostGIS at %s with about %d places", describe(url), db.count())
        app.state.repo = db
        try:
            yield
        finally:
            db.close()
        return
    path = Path(os.environ.get("DATA_FILE", DEFAULT_DATA_FILE))
    if not path.is_file():
        raise RuntimeError(f"Data file {path} not found. Run data/download.sh or set DATA_FILE.")
    start = time.perf_counter()
    memory = PlaceRepository()
    memory.load(path)
    logger.info(
        "Loaded %d places from %s in %.1f s", len(memory), path, time.perf_counter() - start
    )
    app.state.repo = memory
    yield


app = FastAPI(
    title="PlaceFinder",
    version=version("placefinder"),
    description=f"Search places by name and location. {ATTRIBUTION}.",
    lifespan=lifespan,
)
add_problem_handlers(app)


# also PoolTimeout: no free connection in the pool within 30 seconds
@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """The database does not answer: 503 with a hint when to try again."""
    logger.error("Database unavailable: %s", exc)
    return problem_response(
        request,
        503,
        "database-unavailable",
        "Database unavailable",
        "The database does not answer at the moment",
        headers={"Retry-After": "30"},
    )


app.include_router(create_router())
# CORS: web pages of these origins may read the responses in the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o],
    allow_methods=["GET"],
    allow_headers=["If-None-Match"],
    expose_headers=["ETag", "Link"],
)


@app.get("/")
def about() -> dict[str, str]:
    """Name, version and data attribution of the service."""
    return {
        "name": app.title,
        "version": app.version,
        "api": "/v1/places",
        "docs": "/docs",
        "attribution": ATTRIBUTION,
    }


@app.get("/health")
def health(repo: Annotated[Repository, Depends(repository)]) -> dict[str, str | int]:
    """Health check; also reports the number of places (estimated with PostGIS)."""
    return {"status": "ok", "places": repo.count()}


@app.get("/places", deprecated=True, tags=["v0"], responses=documented(422))
def search_places(
    response: Response,
    repo: Annotated[Repository, Depends(repository)],
    q: Annotated[
        str,
        Query(min_length=1, max_length=100, description="Name or beginning of a name, e.g. Erfurt"),
    ],
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum number of results")] = 10,
) -> list[Place]:
    """Version 0, deprecated: use GET /v1/places.

    Find places whose name, ASCII name or an alternate name starts with q.
    Exact matches come first, then larger places.
    """
    response.headers.update(V0_HEADERS)
    hits = repo.find(SearchQuery(sort="relevance", limit=limit, q=q))
    places = [hit.place for hit in hits[:limit]]
    logger.debug("Search %r: %d of at most %d places", q, len(places), limit)
    return places


@app.get("/places/{place_id}", deprecated=True, tags=["v0"], responses=documented(404, 422))
def get_place(
    place_id: Annotated[int, PathParam(description="GeoNames id", examples=[2929670])],
    response: Response,
    repo: Annotated[Repository, Depends(repository)],
) -> Place:
    """Version 0, deprecated: use GET /v1/places/{place_id}."""
    place = repo.get(place_id)
    if place is None:
        raise Problem(404, "place-not-found", "Place not found", f"No place with id {place_id}")
    response.headers.update(V0_HEADERS)
    return place
