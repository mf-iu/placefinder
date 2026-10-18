"""Places from a GeoNames dump file, kept in memory.

GeoNames dumps (e.g. cities15000.txt) are tab-separated text files with one
place per line and 19 columns, described at
https://download.geonames.org/export/dump/readme.txt
"""

import sys
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


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


def parse_line(line: str) -> tuple[Place, set[str]]:
    """Parse one line of a GeoNames dump into a place and all its names."""
    f = line.rstrip("\n").split("\t")
    place = Place(
        id=int(f[0]),
        name=f[1],
        latitude=float(f[4]),
        longitude=float(f[5]),
        # values that repeat in many lines share one string object (saves memory)
        country_code=sys.intern(f[8]),
        population=int(f[14] or 0),
        feature_code=sys.intern(f[7]),
        timezone=sys.intern(f[17]),
    )
    # name, ASCII name and the comma-separated alternate names
    # (e.g. "München" for the GeoNames name "Munich")
    names = {f[1], f[2], *f[3].split(",")}
    names.discard("")
    return place, names


def normalize(name: str) -> str:
    """Normalize a name for case-insensitive comparison."""
    return name.strip().casefold()


class PlaceRepository:
    """In-memory place store with a sorted name index for prefix search."""

    def __init__(self) -> None:
        self._places: dict[int, Place] = {}
        # parallel lists, sorted by key: normalized name -> place id
        self._keys: list[str] = []
        self._ids: list[int] = []

    def __len__(self) -> int:
        return len(self._places)

    def load(self, path: str | Path) -> None:
        """Replace the content with the places of a GeoNames dump file."""
        with open(path, encoding="utf-8") as lines:
            self.replace(parse_line(line) for line in lines if line.strip())

    def replace(self, entries: Iterable[tuple[Place, set[str]]]) -> None:
        """Replace the content with the given places and their names."""
        places: dict[int, Place] = {}
        index: list[tuple[str, int]] = []
        for place, names in entries:
            places[place.id] = place
            index.extend((key, place.id) for key in {normalize(name) for name in names})
        index.sort()
        self._places = places
        self._keys = [key for key, _ in index]
        self._ids = [place_id for _, place_id in index]

    def get(self, place_id: int) -> Place | None:
        """Return the place with this GeoNames id, or None."""
        return self._places.get(place_id)

    def all(self) -> Iterable[Place]:
        """All places, in no particular order."""
        return self._places.values()

    def matches(self, q: str) -> dict[int, int]:
        """Ids of the places whose name starts with q, ignoring case, each with a
        rank: 0 if a name equals q, 1 if a name only starts with q."""
        prefix = normalize(q)
        if not prefix:
            return {}
        ranks: dict[int, int] = {}
        # binary search for the first key >= prefix; all matching keys follow
        # it, and keys equal to the prefix come before longer ones
        i = bisect_left(self._keys, prefix)
        while i < len(self._keys) and self._keys[i].startswith(prefix):
            ranks.setdefault(self._ids[i], 0 if self._keys[i] == prefix else 1)
            i += 1
        return ranks

    def search(self, q: str, limit: int = 10) -> list[Place]:
        """Find places whose name starts with q, ignoring case.

        Exact name matches come first, then by population (largest first).
        """
        ranks = self.matches(q)
        found = [self._places[place_id] for place_id in ranks]
        found.sort(key=lambda p: (ranks[p.id], -p.population, p.id))
        return found[:limit]
