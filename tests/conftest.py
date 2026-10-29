"""Fixtures: the API with the places in memory and, if TEST_DATABASE_URL is
set, a second time with the same places in PostgreSQL with PostGIS.

TEST_DATABASE_URL must point to a database in which the user may create
schemas and the extensions postgis and pg_trgm, e.g. the service db of
compose.yaml: TEST_DATABASE_URL=postgresql://pf:pf@localhost:5432/pf
The tests use a schema of their own and drop it afterwards.
"""

import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from geonames_sample import SAMPLE
from psycopg.conninfo import make_conninfo

from placefinder.main import app

# as 06-postgis/schema.sql and indexes.sql of cloud-labs-local
TABLE = """
CREATE TABLE places (
    geonameid integer PRIMARY KEY, name text NOT NULL, asciiname text,
    alternatenames text, latitude double precision NOT NULL,
    longitude double precision NOT NULL, feature_class char(1), feature_code text,
    country_code char(2), cc2 text, admin1_code text, admin2_code text,
    admin3_code text, admin4_code text, population bigint, elevation integer,
    dem integer, timezone text, modification_date date)"""
GEOMETRY = """
ALTER TABLE places ADD COLUMN geom geography(Point, 4326)
  GENERATED ALWAYS AS (ST_MakePoint(longitude, latitude)::geography) STORED;
CREATE INDEX ON places USING gist (geom);
CREATE INDEX ON places USING gin (name gin_trgm_ops);
CREATE INDEX ON places USING gin ((',' || lower(name) || ',' || lower(coalesce(asciiname, ''))
  || ',' || lower(coalesce(alternatenames, '')) || ',') gin_trgm_ops);
ANALYZE places"""


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    path = tmp_path / "places.txt"
    path.write_text("".join(SAMPLE), encoding="utf-8")
    return path


def schema_with_places(url: str, with_table: bool = True) -> Iterator[str]:
    """Create a schema of its own, optionally with the sample places, and yield
    a connection string that uses it; without the table, the search path does
    not include public either, where a table places may exist."""
    schema = f"pf_test_{secrets.token_hex(4)}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path = {schema}, public")
        if with_table:
            conn.execute(TABLE)
            # the same COPY as load-cities.sh: tabs, empty fields become NULL
            copy = "COPY places FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01')"
            with conn.cursor().copy(copy) as data:
                data.write("".join(SAMPLE))
            for statement in GEOMETRY.split(";"):
                conn.execute(statement)
    try:
        path = f"{schema},public" if with_table else schema
        yield make_conninfo(url, options=f"-c search_path={path}")
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture(scope="session")
def postgis_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostGIS tests need TEST_DATABASE_URL")
    yield from schema_with_places(url)


@pytest.fixture(params=["memory", "postgis"])
def client(
    request: pytest.FixtureRequest, data_file: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    if request.param == "postgis":
        monkeypatch.setenv("DATABASE_URL", request.getfixturevalue("postgis_url"))
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DATA_FILE", str(data_file))
    # the with block runs the lifespan, which chooses and opens the place store
    with TestClient(app) as client:
        yield client
