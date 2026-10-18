"""Tests of the REST API version 1 (/v1): GeoJSON, filters, pagination,
caching headers, ETags and problem details."""

import pytest
from fastapi.testclient import TestClient

GEOJSON = "application/geo+json"
PROBLEM = "application/problem+json"
ERFURT = 2929670


def names(response) -> list[str]:
    return [f["properties"]["name"] for f in response.json()["features"]]


def test_search_returns_feature_collection(client: TestClient) -> None:
    response = client.get("/v1/places", params={"q": "Erfurt"})
    assert response.status_code == 200
    assert response.headers["content-type"] == GEOJSON
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=300"
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["links"] == [
        {"rel": "self", "type": GEOJSON, "href": "/v1/places?q=Erfurt"},
    ]
    assert body["features"] == [
        {
            "type": "Feature",
            "id": ERFURT,
            # GeoJSON: longitude before latitude
            "geometry": {"type": "Point", "coordinates": [11.03536, 50.97734]},
            "properties": {
                "name": "Erfurt",
                "country_code": "DE",
                "population": 218793,
                "feature_code": "PPLA",
                "timezone": "Europe/Berlin",
            },
            "links": [{"rel": "self", "type": GEOJSON, "href": f"/v1/places/{ERFURT}"}],
        }
    ]


def test_search_by_name_ranks_exact_matches_first(client: TestClient) -> None:
    assert names(client.get("/v1/places", params={"q": "frankfurt"})) == [
        "Frankfurt am Main",
        "Frankfurt (Oder)",
    ]
    assert names(client.get("/v1/places", params={"q": "Wien"})) == ["Vienna"]


def test_search_without_filter_sorts_by_population(client: TestClient) -> None:
    assert names(client.get("/v1/places", params={"limit": 3})) == [
        "Vienna",
        "Munich",
        "Frankfurt am Main",
    ]


def test_search_around_a_point_adds_distance(client: TestClient) -> None:
    # 25 km around Erfurt: Erfurt itself and Weimar, nearest first
    response = client.get("/v1/places", params={"lon": 11.03, "lat": 50.98, "radius": 25000})
    assert names(response) == ["Erfurt", "Weimar"]
    distances = [f["properties"]["distance"] for f in response.json()["features"]]
    assert distances[0] < 1000
    assert 20000 < distances[1] < 22000


def test_search_within_bounding_box(client: TestClient) -> None:
    # Thuringia and Franconia: Erfurt, Weimar, Erlangen
    response = client.get("/v1/places", params={"bbox": "10.5,49.5,11.5,51.1", "sort": "name"})
    assert names(response) == ["Erfurt", "Erlangen", "Weimar"]


def test_search_by_country(client: TestClient) -> None:
    assert names(client.get("/v1/places", params={"country": "at"})) == ["Vienna"]


def test_filters_combine(client: TestClient) -> None:
    params = {"q": "Er", "bbox": "10.5,50.5,11.5,51.5"}
    assert names(client.get("/v1/places", params=params)) == ["Erfurt"]


def test_cursor_pagination_returns_every_place_once(client: TestClient) -> None:
    seen = []
    response = client.get("/v1/places", params={"limit": 3})
    while True:
        seen += names(response)
        links = {link["rel"]: link["href"] for link in response.json()["links"]}
        if "next" not in links:
            assert "link" not in response.headers
            break
        assert response.headers["link"] == f'<{links["next"]}>; rel="next"'
        assert "limit=3" in links["next"]
        response = client.get(links["next"])
    assert len(seen) == 7
    assert len(set(seen)) == 7


def test_next_link_repeats_the_parameters(client: TestClient) -> None:
    response = client.get("/v1/places", params={"bbox": "5,45,17,55", "limit": 2})
    next_href = response.json()["links"][1]["href"]
    assert next_href.startswith("/v1/places?bbox=5,45,17,55&limit=2&cursor=")
    assert response.headers["link"] == f'<{next_href}>; rel="next"'


@pytest.mark.parametrize(
    ("params", "problem"),
    [
        ({"bbox": "11.0,50.9"}, "invalid-bbox"),
        ({"bbox": "a,b,c,d"}, "invalid-bbox"),
        ({"bbox": "11.5,50.0,10.5,51.0"}, "invalid-bbox"),
        ({"bbox": "10,50,200,51"}, "invalid-bbox"),
        ({"lon": 11.03}, "invalid-parameters"),
        ({"lon": 11.03, "lat": 50.98, "radius": 50001}, "invalid-parameters"),
        ({"sort": "distance"}, "invalid-parameters"),
        ({"sort": "relevance"}, "invalid-parameters"),
        ({"limit": 101}, "invalid-parameters"),
        ({"country": "DEU"}, "invalid-parameters"),
        ({"cursor": "not-a-cursor"}, "invalid-cursor"),
    ],
)
def test_invalid_parameters_return_problem_details(
    client: TestClient, params: dict, problem: str
) -> None:
    response = client.get("/v1/places", params=params)
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == f"https://placefinder.test/problems/{problem}"
    assert body["status"] == 422
    assert body["instance"] == "/v1/places"
    assert body["title"]


def test_invalid_bbox_names_the_parameter(client: TestClient) -> None:
    body = client.get("/v1/places", params={"bbox": "11.0,50.9"}).json()
    assert body["detail"] == "bbox needs 4 numbers, got 2"
    assert body["parameter"] == "bbox"


def test_cursor_of_another_sort_order_is_rejected(client: TestClient) -> None:
    first = client.get("/v1/places", params={"limit": 1}).json()
    cursor = first["links"][1]["href"].split("cursor=")[1]
    response = client.get("/v1/places", params={"sort": "name", "cursor": cursor})
    assert response.json()["type"].endswith("/invalid-cursor")


def test_get_place_as_feature_with_etag(client: TestClient) -> None:
    response = client.get(f"/v1/places/{ERFURT}")
    assert response.status_code == 200
    assert response.headers["content-type"] == GEOJSON
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert response.headers["etag"].startswith('"')
    assert response.json()["properties"]["name"] == "Erfurt"


def test_conditional_request_returns_304(client: TestClient) -> None:
    etag = client.get(f"/v1/places/{ERFURT}").headers["etag"]
    for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        response = client.get(f"/v1/places/{ERFURT}", headers={"If-None-Match": header})
        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == etag
    changed = client.get(f"/v1/places/{ERFURT}", headers={"If-None-Match": '"v7"'})
    assert changed.status_code == 200


def test_unknown_place_returns_problem(client: TestClient) -> None:
    response = client.get("/v1/places/1")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    assert response.json() == {
        "type": "https://placefinder.test/problems/place-not-found",
        "title": "Place not found",
        "status": 404,
        "detail": "No place with id 1",
        "instance": "/v1/places/1",
    }


def test_unknown_path_and_method_return_problems(client: TestClient) -> None:
    response = client.get("/v2/places")
    assert response.status_code == 404
    assert response.json()["type"] == "about:blank"
    response = client.post("/v1/places")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.headers["content-type"] == PROBLEM


def test_cors_allows_the_local_map(client: TestClient) -> None:
    origin = "http://localhost:5173"
    response = client.get("/v1/places", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin
    preflight = client.options(
        "/v1/places",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "If-None-Match",
        },
    )
    assert preflight.status_code == 200
    other = client.get("/v1/places", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in other.headers


def test_openapi_describes_v1(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    get_place = spec["paths"]["/v1/places/{place_id}"]["get"]
    assert GEOJSON in get_place["responses"]["200"]["content"]
    assert PROBLEM in get_place["responses"]["404"]["content"]
    assert set(get_place["responses"]) == {"200", "304", "404", "422"}


@pytest.mark.parametrize(
    "key", ['["-population",["a",1]]', '["-population",[1]]', '["name",[1,2]]', "[1]", "{}"]
)
def test_forged_cursors_are_rejected(client: TestClient, key: str) -> None:
    import base64

    cursor = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
    sort = "name" if '"name"' in key else "-population"
    response = client.get("/v1/places", params={"cursor": cursor, "sort": sort})
    assert response.status_code == 422
    assert response.json()["type"].endswith("/invalid-cursor")
