"""Cache-aside for search results in Valkey (from session 7).

The places change rarely: load-cities.sh loads them once, a new load replaces
them. Searches, on the other hand, repeat all the time - the map asks for the
same bounding boxes again and again. PlaceFinder therefore keeps the answer of
each search in Valkey for a few minutes (cache-aside):

1. Look up the key of the request. A hit answers without asking the store.
2. On a miss, ask the store (memory or PostGIS), then save the answer with a
   time to live (TTL). After the TTL Valkey deletes it on its own.

The key is the path with the query string exactly as the client sent it, e.g.
placefinder:v1:/v1/places?bbox=10.9,50.9,11.2,51.1&limit=100. Valkey
keeps keys and values in memory; with maxmemory and the policy allkeys-lru in
compose.yaml it drops the least recently used keys when the memory is full.

The cache is optional. Without VALKEY_URL there is none. If Valkey does not
answer, PlaceFinder logs a warning and asks the store (fail open): a cache may
make the service faster, never unavailable.
"""

import json
import logging
from typing import Any
from urllib.parse import urlsplit

import valkey
from valkey.exceptions import ValkeyError

logger = logging.getLogger("uvicorn.error")

PREFIX = "placefinder:v1:"


def describe(url: str) -> str:
    """Host, port and database number of a Valkey URL, without the password."""
    parts = urlsplit(url)
    return f"{parts.hostname or 'localhost'}:{parts.port or 6379}{parts.path or '/0'}"


class SearchCache:
    """Answers of searches in Valkey, as JSON with a time to live."""

    def __init__(self, url: str, ttl: int = 300, client: Any = None) -> None:
        self.url = url
        self.ttl = ttl
        # short timeouts: a slow cache would make every search slow
        self.client = client or valkey.Valkey.from_url(
            url, socket_connect_timeout=0.2, socket_timeout=0.2
        )
        self.available = True  # to log a failure once, not on every request

    def key(self, path_and_query: str) -> str:
        return PREFIX + path_and_query

    def get(self, key: str) -> dict[str, Any] | None:
        """The saved answer, or None on a miss or if Valkey does not answer."""
        try:
            raw = self.client.get(key)
        except ValkeyError as exc:
            self._failed(exc)
            return None
        self._answered()
        return json.loads(raw) if raw is not None else None

    def put(self, key: str, value: dict[str, Any]) -> bool:
        """Save an answer with the TTL; False if Valkey does not answer."""
        try:
            self.client.set(key, json.dumps(value, separators=(",", ":")), ex=self.ttl)
        except ValkeyError as exc:
            self._failed(exc)
            return False
        self._answered()
        return True

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except ValkeyError:
            return False

    def close(self) -> None:
        self.client.close()

    def _failed(self, exc: Exception) -> None:
        if self.available:
            logger.warning("Cache unavailable, searches go to the store: %s", exc)
        self.available = False

    def _answered(self) -> None:
        if not self.available:
            logger.info("Cache available again")
        self.available = True
