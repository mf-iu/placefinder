"""Geometry helpers: bounding boxes and distances on the sphere (WGS 84)."""

from math import asin, cos, radians, sin, sqrt
from typing import NamedTuple

EARTH_RADIUS_M = 6_371_008.8  # mean radius of the earth in meters


class BBox(NamedTuple):
    """Bounding box in the order of GeoJSON and OGC API: lon, lat, lon, lat."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def contains(self, lon: float, lat: float) -> bool:
        return self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat


def distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters (haversine formula)."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(a)))


def around(lon: float, lat: float, radius_m: float) -> BBox:
    """A box that contains the circle; a cheap filter before distance_m."""
    dlat = radius_m / 111_195  # meters per degree of latitude
    dlon = dlat / max(cos(radians(lat)), 0.01)
    return BBox(lon - dlon, max(-90.0, lat - dlat), lon + dlon, min(90.0, lat + dlat))
