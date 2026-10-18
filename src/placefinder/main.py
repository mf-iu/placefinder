"""PlaceFinder API: search places of a GeoNames dump in memory.

Version 1 under /v1 (from session 5): GeoJSON, filters, cursor pagination,
ETags and errors as problem details. The unversioned endpoints of stage v0
(/places) remain for a while and are marked as deprecated.

Start for development:  uv run fastapi dev src/placefinder/main.py
Start for production:   uvicorn placefinder.main:app --host 0.0.0.0 --port 8000
Settings: DATA_FILE (GeoNames text file), LOG_LEVEL (default info),
CORS_ORIGINS (origins of web pages that may call the API)
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Response
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware

from placefinder.api import create_router
from placefinder.places import Place, PlaceRepository
from placefinder.problems import Problem, add_problem_handlers, documented

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
repo = PlaceRepository()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the places once at startup, before the first request."""
    path = Path(os.environ.get("DATA_FILE", DEFAULT_DATA_FILE))
    if not path.is_file():
        raise RuntimeError(f"Data file {path} not found. Run data/download.sh or set DATA_FILE.")
    start = time.perf_counter()
    repo.load(path)
    logger.info("Loaded %d places from %s in %.1f s", len(repo), path, time.perf_counter() - start)
    yield


app = FastAPI(
    title="PlaceFinder",
    version=version("placefinder"),
    description=f"Search places by name and location. {ATTRIBUTION}.",
    lifespan=lifespan,
)
add_problem_handlers(app)
app.include_router(create_router(repo))
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
def health() -> dict[str, str | int]:
    """Liveness check; also reports the number of loaded places."""
    return {"status": "ok", "places": len(repo)}


@app.get("/places", deprecated=True, tags=["v0"], responses=documented(422))
def search_places(
    response: Response,
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
    places = repo.search(q, limit)
    logger.debug("Search %r: %d of at most %d places", q, len(places), limit)
    return places


@app.get("/places/{place_id}", deprecated=True, tags=["v0"], responses=documented(404, 422))
def get_place(
    place_id: Annotated[int, PathParam(description="GeoNames id", examples=[2929670])],
    response: Response,
) -> Place:
    """Version 0, deprecated: use GET /v1/places/{place_id}."""
    place = repo.get(place_id)
    if place is None:
        raise Problem(404, "place-not-found", "Place not found", f"No place with id {place_id}")
    response.headers.update(V0_HEADERS)
    return place
