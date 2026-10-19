"""Tests of the cache for searches (cache.py): cache-aside, Cache-Status
(RFC 9211), time to live and the fallback when Valkey does not answer.

Most tests use a small fake of the Valkey client. With TEST_VALKEY_URL set
(e.g. valkey://localhost:6379/15), one test also runs against a real Valkey.
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from valkey.exceptions import ConnectionError as ValkeyConnectionError

from placefinder.cache import PREFIX, SearchCache, describe
from placefinder.main import app

MISS = "PlaceFinder; fwd=uri-miss; stored"
HIT = "PlaceFinder; hit"


class FakeValkey:
    """The four commands the cache uses, in a dict."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int) -> bool:
        self.data[key] = value
        self.ttl[key] = ex
        return True

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        pass


class DownValkey(FakeValkey):
    """A Valkey that does not answer."""

    def get(self, key: str) -> str | None:
        raise ValkeyConnectionError("Connection refused")

    def set(self, key: str, value: str, ex: int) -> bool:
        raise ValkeyConnectionError("Connection refused")

    def ping(self) -> bool:
        raise ValkeyConnectionError("Connection refused")


@pytest.fixture
def fake() -> FakeValkey:
    return FakeValkey()


@pytest.fixture
def cached(client: TestClient, fake: FakeValkey) -> Iterator[TestClient]:
    """The API of the fixture client, with a cache in the fake Valkey."""
    client.app.state.cache = SearchCache("valkey://fake", client=fake)
    yield client
    client.app.state.cache = None


def test_second_search_comes_from_cache(cached: TestClient, fake: FakeValkey) -> None:
    first = cached.get("/v1/places", params={"q": "Erfurt"})
    second = cached.get("/v1/places", params={"q": "Erfurt"})
    assert first.headers["cache-status"] == MISS
    assert second.headers["cache-status"] == HIT
    assert second.json() == first.json()
    assert second.headers["content-type"] == "application/geo+json"
    assert second.headers["cache-control"] == first.headers["cache-control"]
    assert list(fake.data) == [PREFIX + "/v1/places?q=Erfurt"]


def test_link_to_next_page_comes_from_cache(cached: TestClient) -> None:
    params = {"country": "DE", "limit": 2}
    first = cached.get("/v1/places", params=params)
    second = cached.get("/v1/places", params=params)
    assert second.headers["cache-status"] == HIT
    assert second.headers["link"] == first.headers["link"]
    assert 'rel="next"' in second.headers["link"]


def test_other_parameters_are_another_key(cached: TestClient, fake: FakeValkey) -> None:
    cached.get("/v1/places", params={"q": "Erfurt"})
    response = cached.get("/v1/places", params={"q": "Erfurt", "limit": 5})
    assert response.headers["cache-status"] == MISS
    assert len(fake.data) == 2


def test_errors_are_not_cached(cached: TestClient, fake: FakeValkey) -> None:
    response = cached.get("/v1/places", params={"limit": 500})
    assert response.status_code == 422
    assert "cache-status" not in response.headers
    assert fake.data == {}


def test_answers_expire_after_the_ttl(cached: TestClient, fake: FakeValkey) -> None:
    cached.get("/v1/places", params={"q": "Erfurt"})
    assert list(fake.ttl.values()) == [300]


def test_without_cache_there_is_no_cache_status(client: TestClient) -> None:
    response = client.get("/v1/places", params={"q": "Erfurt"})
    assert response.status_code == 200
    assert "cache-status" not in response.headers


def test_unavailable_cache_falls_back_to_the_store(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.app.state.cache = SearchCache("valkey://down", client=DownValkey())
    try:
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            responses = [client.get("/v1/places", params={"q": "Erfurt"}) for _ in range(3)]
        assert [r.status_code for r in responses] == [200, 200, 200]
        assert responses[0].headers["cache-status"] == "PlaceFinder; fwd=uri-miss"
        assert responses[0].json()["features"][0]["properties"]["name"] == "Erfurt"
        # one warning, not one per request
        assert caplog.text.count("Cache unavailable") == 1
        assert client.get("/health").json()["cache"] == "unavailable"
    finally:
        client.app.state.cache = None


def test_health_reports_the_cache(cached: TestClient) -> None:
    assert cached.get("/health").json()["cache"] == "ok"


def test_start_without_valkey(data_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_FILE", str(data_file))
    monkeypatch.setenv("VALKEY_URL", "valkey://127.0.0.1:1/0")  # nothing listens there
    with TestClient(app) as client:
        assert client.get("/health").json()["cache"] == "unavailable"
        response = client.get("/v1/places", params={"q": "Erfurt"})
        assert response.status_code == 200
        assert response.headers["cache-status"] == "PlaceFinder; fwd=uri-miss"


def test_describe_hides_the_password() -> None:
    assert describe("valkey://:secret@cache:6380/1") == "cache:6380/1"
    assert describe("valkey://localhost") == "localhost:6379/0"


def test_real_valkey(data_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("TEST_VALKEY_URL")
    if not url:
        pytest.skip("Valkey tests need TEST_VALKEY_URL")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_FILE", str(data_file))
    monkeypatch.setenv("VALKEY_URL", url)
    monkeypatch.setenv("CACHE_TTL", "60")
    with TestClient(app) as client:
        cache = client.app.state.cache
        key = cache.key("/v1/places?q=Erf&limit=3")
        cache.client.delete(key)
        try:
            first = client.get("/v1/places", params={"q": "Erf", "limit": 3})
            second = client.get("/v1/places", params={"q": "Erf", "limit": 3})
            assert first.headers["cache-status"] == MISS
            assert second.headers["cache-status"] == HIT
            assert 0 < cache.client.ttl(key) <= 60
        finally:
            cache.client.delete(key)
