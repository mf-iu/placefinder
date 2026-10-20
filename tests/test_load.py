"""Loading a GeoNames file into an empty database (load.py), by hand and at
startup with DATABASE_INIT. Needs TEST_DATABASE_URL with a user who may create
databases, e.g. the service db of compose.yaml; each test gets a database of
its own."""

import os
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from geonames_sample import SAMPLE
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from placefinder import load as load_module
from placefinder.load import load
from placefinder.main import app


@pytest.fixture
def empty_db() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Loading needs TEST_DATABASE_URL")
    name = f"pf_load_{secrets.token_hex(4)}"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {name}")
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("The user of TEST_DATABASE_URL may not create databases")
    try:
        yield make_conninfo(url, dbname=name)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE {name} WITH (FORCE)")


def test_load_once(empty_db: str, data_file: Path) -> None:
    assert load(empty_db, data_file) == len(SAMPLE)
    # the table exists: nothing to do
    assert load(empty_db, data_file) == 0
    assert load(empty_db, data_file, replace=True) == len(SAMPLE)
    with psycopg.connect(empty_db) as conn:
        indexes = {
            row[0]
            for row in conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'places'")
        }
    assert {"places_geom_idx", "places_all_names_trgm_idx"} <= indexes


def test_failed_load_leaves_nothing(empty_db: str, tmp_path: Path) -> None:
    broken = tmp_path / "broken.txt"
    broken.write_text("not\ta\tplace\n", encoding="utf-8")
    with pytest.raises(psycopg.Error):
        load(empty_db, broken)
    with psycopg.connect(empty_db) as conn:
        assert conn.execute("SELECT to_regclass('places')").fetchone() == (None,)


def test_database_init_at_startup(
    empty_db: str, data_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_db)
    monkeypatch.setenv("DATABASE_INIT", "true")
    monkeypatch.setenv("DATA_FILE", str(data_file))
    with TestClient(app) as client:
        assert client.get("/health").json()["places"] == len(SAMPLE)
        names = [
            f["properties"]["name"]
            for f in client.get("/v1/places", params={"q": "Erfurt"}).json()["features"]
        ]
        assert names[0] == "Erfurt"


def test_command(
    empty_db: str,
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_db)
    monkeypatch.setattr(sys, "argv", ["placefinder-load", str(data_file)])
    with caplog.at_level("INFO", logger="uvicorn.error"):
        load_module.main()
    assert f"Loaded {len(SAMPLE)} places" in caplog.text
    assert conninfo_to_dict(empty_db)["dbname"] in caplog.text  # host and database, no password
