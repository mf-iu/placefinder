import logging
import os

import pytest
from conftest import schema_with_places
from fastapi.testclient import TestClient

from placefinder.main import app


def test_health_reports_loaded_places(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "places": 7}


def test_livez_answers_without_the_data(client: TestClient) -> None:
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_about_contains_attribution(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["name"] == "PlaceFinder"
    assert "GeoNames" in body["attribution"]


def test_search_returns_place_fields(client: TestClient) -> None:
    response = client.get("/places", params={"q": "Erfurt"})
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 2929670,
            "name": "Erfurt",
            "latitude": 50.97734,
            "longitude": 11.03536,
            "country_code": "DE",
            "population": 218793,
            "feature_code": "PPLA",
            "timezone": "Europe/Berlin",
        }
    ]


def test_search_ignores_case_and_spaces(client: TestClient) -> None:
    names = [p["name"] for p in client.get("/places", params={"q": "  erFURT "}).json()]
    assert names == ["Erfurt"]


def test_search_finds_alternate_names(client: TestClient) -> None:
    names = [p["name"] for p in client.get("/places", params={"q": "München"}).json()]
    assert names == ["Munich"]


def test_search_orders_by_population(client: TestClient) -> None:
    names = [p["name"] for p in client.get("/places", params={"q": "Frankfurt"}).json()]
    assert names == ["Frankfurt am Main", "Frankfurt (Oder)"]


def test_search_matches_beginning_of_names(client: TestClient) -> None:
    names = [p["name"] for p in client.get("/places", params={"q": "Er"}).json()]
    assert names == ["Erfurt", "Erlangen"]
    names = [p["name"] for p in client.get("/places", params={"q": "Mün"}).json()]
    assert names == ["Munich"]


def test_search_respects_limit(client: TestClient) -> None:
    places = client.get("/places", params={"q": "Er", "limit": 1}).json()
    assert len(places) == 1


def test_search_without_match_returns_empty_list(client: TestClient) -> None:
    assert client.get("/places", params={"q": "Atlantis"}).json() == []


@pytest.mark.parametrize(
    "params", [{}, {"q": ""}, {"q": "Erfurt", "limit": 0}, {"q": "Erfurt", "limit": 101}]
)
def test_search_rejects_invalid_parameters(client: TestClient, params: dict) -> None:
    assert client.get("/places", params=params).status_code == 422


def test_get_place_by_id(client: TestClient) -> None:
    response = client.get("/places/2867714")
    assert response.status_code == 200
    assert response.json()["name"] == "Munich"


def test_get_unknown_place_returns_404(client: TestClient) -> None:
    response = client.get("/places/1")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "No place with id 1"


def test_v0_is_marked_as_deprecated(client: TestClient) -> None:
    response = client.get("/places", params={"q": "Erfurt"})
    assert response.headers["deprecation"] == "@1790812800"
    assert response.headers["sunset"] == "Fri, 01 Jan 2027 00:00:00 GMT"
    assert 'rel="successor-version"' in response.headers["link"]
    assert client.get("/openapi.json").json()["paths"]["/places"]["get"]["deprecated"] is True


def test_startup_fails_without_data_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "missing.txt"))
    with pytest.raises(RuntimeError, match="data/download.sh"), TestClient(app):
        pass


def test_startup_fails_without_table(monkeypatch) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostGIS tests need TEST_DATABASE_URL")
    for conninfo in schema_with_places(url, with_table=False):
        monkeypatch.setenv("DATABASE_URL", conninfo)
        with pytest.raises(RuntimeError, match="load-cities.sh"), TestClient(app):
            pass


def test_startup_fails_at_once_without_database(monkeypatch) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostGIS tests need TEST_DATABASE_URL")
    from psycopg import OperationalError
    from psycopg.conninfo import make_conninfo

    monkeypatch.setenv("DATABASE_URL", make_conninfo(url, dbname="pf_no_such_database"))
    with pytest.raises(OperationalError, match="does not exist"), TestClient(app):
        pass


def test_search_logs_at_debug_level(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="uvicorn.error")
    client.get("/places", params={"q": "Erfurt"})
    assert "Search 'Erfurt': 1 of at most 10 places" in caplog.text


def test_unavailable_database_returns_503(client: TestClient, monkeypatch) -> None:
    from psycopg import OperationalError

    def fail(*args, **kwargs):
        raise OperationalError("connection lost")

    monkeypatch.setattr(client.app.state.repo, "find", fail)
    response = client.get("/v1/places", params={"q": "Erfurt"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.json()["type"].endswith("/database-unavailable")


def test_search_with_nul_byte_finds_nothing(client: TestClient) -> None:
    assert client.get("/v1/places", params={"q": "Er\x00furt"}).json()["features"] == []
