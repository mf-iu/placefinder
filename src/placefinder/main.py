"""PlaceFinder API, stage v0: search places of a GeoNames dump in memory.

Start for development:  uv run fastapi dev src/placefinder/main.py
Start for production:   uvicorn placefinder.main:app --host 0.0.0.0 --port 8000
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from placefinder.places import Place, PlaceRepository

# default data file, relative to the working directory; override with DATA_FILE
DEFAULT_DATA_FILE = "data/cities15000.txt"
ATTRIBUTION = "Place data: GeoNames (https://www.geonames.org), CC BY 4.0"

# uvicorn configures this logger, so its messages appear in the server output
logger = logging.getLogger("uvicorn.error")
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
    description=f"Search places by name. {ATTRIBUTION}.",
    lifespan=lifespan,
)


@app.get("/")
def about() -> dict[str, str]:
    """Name, version and data attribution of the service."""
    return {"name": app.title, "version": app.version, "docs": "/docs", "attribution": ATTRIBUTION}


@app.get("/health")
def health() -> dict[str, str | int]:
    """Liveness check; also reports the number of loaded places."""
    return {"status": "ok", "places": len(repo)}


@app.get("/places")
def search_places(
    q: Annotated[
        str,
        Query(min_length=1, max_length=100, description="Name or beginning of a name, e.g. Erfurt"),
    ],
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum number of results")] = 10,
) -> list[Place]:
    """Find places whose name, ASCII name or an alternate name starts with q.

    Exact matches come first, then larger places.
    """
    return repo.search(q, limit)


@app.get("/places/{place_id}", responses={404: {"description": "Place not found"}})
def get_place(place_id: int) -> Place:
    """Return one place by its GeoNames id."""
    place = repo.get(place_id)
    if place is None:
        raise HTTPException(status_code=404, detail=f"No place with id {place_id}")
    return place
