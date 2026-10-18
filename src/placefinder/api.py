"""REST API version 1: places as GeoJSON (RFC 7946) with filters, cursor
pagination, caching headers and ETags. Errors are problem details (RFC 9457).
"""

import base64
import binascii
import hashlib
import json
import logging
from bisect import bisect_right
from collections.abc import Callable
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from placefinder.geo import BBox, around, distance_m
from placefinder.places import Place, PlaceRepository, normalize
from placefinder.problems import Problem, documented

MEDIA_TYPE = "application/geo+json"
logger = logging.getLogger("uvicorn.error")
MAX_RADIUS_M = 50_000
SEARCH_CACHE = "public, max-age=60, stale-while-revalidate=300"
PLACE_CACHE = "public, max-age=3600"


class GeoJSONResponse(JSONResponse):
    media_type = MEDIA_TYPE


# ---- models: they describe the responses in the OpenAPI document ----


class Point(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # longitude, latitude


class PlaceProperties(BaseModel):
    name: str
    country_code: str
    population: int
    feature_code: str
    timezone: str
    distance: int | None = None  # meters, only with lon and lat


class Link(BaseModel):
    rel: str
    href: str
    type: str | None = None


class Feature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: int
    geometry: Point
    properties: PlaceProperties
    links: list[Link]


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature]
    links: list[Link]


def feature(place: Place, distance: float | None = None) -> dict[str, Any]:
    """A place as GeoJSON feature; coordinates in the order lon, lat."""
    properties: dict[str, Any] = {
        "name": place.name,
        "country_code": place.country_code,
        "population": place.population,
        "feature_code": place.feature_code,
        "timezone": place.timezone,
    }
    if distance is not None:
        properties["distance"] = round(distance)
    return {
        "type": "Feature",
        "id": place.id,
        "geometry": {"type": "Point", "coordinates": [place.longitude, place.latitude]},
        "properties": properties,
        "links": [{"rel": "self", "type": MEDIA_TYPE, "href": f"/v1/places/{place.id}"}],
    }


# ---- parameters that need more checks than FastAPI can do alone ----


NUMBER = r"-?\d{1,3}(\.\d+)?"
BBOX_PATTERN = rf"^{NUMBER}(,{NUMBER}){{3}}$"


def parse_bbox(
    bbox: Annotated[
        str | None,
        Query(
            description="minLon,minLat,maxLon,maxLat, e.g. 10.9,50.9,11.2,51.1",
            # only documented; parse_bbox checks it and explains errors itself
            json_schema_extra={"pattern": BBOX_PATTERN},
        ),
    ] = None,
) -> BBox | None:
    """Read the parameter bbox; raise Problem if it is not a valid box."""
    if bbox is None:
        return None
    parts = bbox.split(",")
    try:
        box = BBox(*map(float, parts))
    except (TypeError, ValueError):
        raise Problem(
            422,
            "invalid-bbox",
            "Invalid bounding box",
            f"bbox needs 4 numbers, got {len(parts)}" if len(parts) != 4 else "bbox needs numbers",
            {"parameter": "bbox"},
        ) from None
    if not (-180 <= box.min_lon <= box.max_lon <= 180 and -90 <= box.min_lat <= box.max_lat <= 90):
        raise Problem(
            422,
            "invalid-bbox",
            "Invalid bounding box",
            "bbox needs minLon <= maxLon in [-180, 180] and minLat <= maxLat in [-90, 90]",
            {"parameter": "bbox"},
        )
    return box


Sort = Literal["relevance", "-population", "name", "distance"]


def encode_cursor(sort: str, key: tuple) -> str:
    """Opaque cursor: the sort order and the sort key of the last feature."""
    raw = json.dumps([sort, list(key)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# types of the sort key per sort order, to check cursors from clients
KEY_TYPES: dict[str, tuple[type | tuple[type, ...], ...]] = {
    "relevance": (int, int, int),
    "-population": (int, int),
    "name": (str, int),
    "distance": ((int, float), int),
}


def decode_cursor(cursor: str, sort: str) -> tuple:
    """Sort key from a cursor; Problem if it is not a cursor for this sort."""
    try:
        if not 0 < len(cursor) <= 200:
            raise ValueError
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        cursor_sort, key = json.loads(raw)
        types = KEY_TYPES[sort]
        if cursor_sort != sort or len(key) != len(types):
            raise ValueError
        if not all(
            isinstance(k, t) and not isinstance(k, bool) for k, t in zip(key, types, strict=True)
        ):
            raise ValueError
        return tuple(key)
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise Problem(
            422,
            "invalid-cursor",
            "Invalid cursor",
            "Use the cursor from the next link with the same parameters",
            {"parameter": "cursor"},
        ) from None


# ---- endpoints ----


def create_router(repo: PlaceRepository) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["v1"])

    @router.get(
        "/places",
        response_model=FeatureCollection,
        response_class=GeoJSONResponse,
        responses=documented(422),
    )
    def search_places(
        request: Request,
        q: Annotated[
            str | None,
            Query(min_length=1, max_length=100, description="Name or beginning of a name"),
        ] = None,
        lon: Annotated[float | None, Query(ge=-180, le=180, description="Longitude")] = None,
        lat: Annotated[float | None, Query(ge=-90, le=90, description="Latitude")] = None,
        radius: Annotated[
            int, Query(ge=1, le=MAX_RADIUS_M, description="Meters around lon, lat")
        ] = 10_000,
        bbox: Annotated[BBox | None, Depends(parse_bbox)] = None,
        country: Annotated[
            str | None, Query(pattern="^[A-Za-z]{2}$", description="ISO 3166 code, e.g. DE")
        ] = None,
        sort: Annotated[
            Sort | None,
            Query(description="Default: relevance with q, distance with lon/lat, else -population"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: Annotated[
            str | None,
            Query(
                description="From the next link of the previous page",
                json_schema_extra={"pattern": "^[A-Za-z0-9_-]{1,200}$"},
            ),
        ] = None,
    ) -> GeoJSONResponse:
        """Search places by name, around a point, within a bounding box and by
        country. All filters combine; results come in pages of `limit`."""
        if (lon is None) != (lat is None):
            raise Problem(
                422, "invalid-parameters", "Invalid parameters", "lon and lat belong together"
            )
        near = lon is not None and lat is not None
        sort = sort or ("relevance" if q else "distance" if near else "-population")
        if (sort == "relevance" and not q) or (sort == "distance" and not near):
            raise Problem(
                422,
                "invalid-parameters",
                "Invalid parameters",
                f"sort={sort} needs {'q' if sort == 'relevance' else 'lon and lat'}",
                {"parameter": "sort"},
            )

        # candidates: the places whose name starts with q, or all places
        ranks: dict[int, int] = {}
        if q:
            ranks = repo.matches(q)
            places = [place for i in ranks if (place := repo.get(i)) is not None]
        else:
            places = list(repo.all())
        if country:
            places = [p for p in places if p.country_code == country.upper()]
        if bbox:
            places = [p for p in places if bbox.contains(p.longitude, p.latitude)]
        distances: dict[int, float] = {}
        if near:
            box = around(lon, lat, radius)
            for p in places:
                if box.contains(p.longitude, p.latitude):
                    d = distance_m(lon, lat, p.longitude, p.latitude)
                    if d <= radius:
                        distances[p.id] = d
            places = [p for p in places if p.id in distances]

        # sort key: unique because the id comes last; equal populations in
        # descending order of the id, like ORDER BY population DESC, id DESC
        keys: dict[str, Callable[[Place], tuple]] = {
            "relevance": lambda p: (ranks[p.id], -p.population, -p.id),
            "-population": lambda p: (-p.population, -p.id),
            "name": lambda p: (normalize(p.name), p.id),
            "distance": lambda p: (round(distances[p.id], 1), p.id),
        }
        key = keys[sort]
        places.sort(key=key)
        start = 0
        if cursor is not None:
            after = decode_cursor(cursor, sort)
            start = bisect_right([key(p) for p in places], after)
        page = places[start : start + limit]

        # links with the same parameters; the cursor marks the position
        self_href = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        links = [{"rel": "self", "type": MEDIA_TYPE, "href": self_href}]
        query = {k: v for k, v in request.query_params.items() if k != "cursor"}
        headers = {"Cache-Control": SEARCH_CACHE}
        if start + limit < len(places):
            next_query = {**query, "cursor": encode_cursor(sort, key(page[-1]))}
            next_href = f"{request.url.path}?{urlencode(next_query, safe=',')}"
            links.append({"rel": "next", "type": MEDIA_TYPE, "href": next_href})
            headers["Link"] = f'<{next_href}>; rel="next"'
        logger.debug("Search %s: %d of %d places", request.url.query, len(page), len(places))
        body = {
            "type": "FeatureCollection",
            "features": [feature(p, distances.get(p.id) if near else None) for p in page],
            "links": links,
        }
        return GeoJSONResponse(body, headers=headers)

    @router.get(
        "/places/{place_id}",
        response_model=Feature,
        response_class=GeoJSONResponse,
        responses={304: {"description": "Not Modified"}, **documented(404, 422)},
    )
    def get_place(
        place_id: Annotated[int, Path(description="GeoNames id", examples=[2929670])],
        request: Request,
    ) -> Response:
        """One place by its GeoNames id, with ETag for conditional requests."""
        place = repo.get(place_id)
        if place is None:
            raise Problem(404, "place-not-found", "Place not found", f"No place with id {place_id}")
        body = feature(place)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        etag = f'"{digest[:16]}"'
        headers = {"ETag": etag, "Cache-Control": PLACE_CACHE}
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return GeoJSONResponse(body, headers=headers)

    return router


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Weak comparison as for If-None-Match (RFC 9110, 13.1.2): W/ is ignored."""
    if not if_none_match:
        return False
    tags = [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]
    return "*" in tags or etag in tags
