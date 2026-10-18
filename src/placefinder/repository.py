"""What the API asks of a place store: a search with filters and keyset
pagination, one place by id and the number of places.

Two implementations: PlaceRepository keeps a GeoNames file in memory
(places.py), PostgisRepository reads the table places in PostgreSQL with
PostGIS (db.py, from session 6).
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from placefinder.geo import BBox

Sort = Literal["relevance", "-population", "name", "distance"]


@dataclass(frozen=True, slots=True)
class Place:
    """A place: GeoNames id, name, WGS 84 coordinates in degrees, ISO country
    code, population, GeoNames feature code (e.g. PPLC for a capital) and
    time zone."""

    id: int
    name: str
    latitude: float
    longitude: float
    country_code: str
    population: int
    feature_code: str
    timezone: str


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Filters, sort order and page of a search; all filters combine."""

    sort: Sort
    limit: int
    q: str | None = None  # name or beginning of a name
    near: tuple[float, float, int] | None = None  # lon, lat, radius in meters
    bbox: BBox | None = None
    country: str | None = None  # ISO 3166 code in capitals
    after: tuple | None = None  # sort key of the last place of the previous page


@dataclass(frozen=True, slots=True)
class Hit:
    """A place found by a search, with its distance in meters (only with near)
    and its sort key, which the next page continues after."""

    place: Place
    distance: float | None
    key: tuple


class Repository(Protocol):
    def find(self, query: SearchQuery) -> list[Hit]:
        """The places after query.after in the sort order, at most query.limit + 1:
        one more than a page, so that the caller knows whether a next page follows."""
        ...

    def get(self, place_id: int) -> Place | None:
        """The place with this GeoNames id, or None."""
        ...

    def count(self) -> int:
        """Number of places, for /health."""
        ...
