from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from geonames_sample import SAMPLE

from placefinder.main import app


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    path = tmp_path / "places.txt"
    path.write_text("".join(SAMPLE), encoding="utf-8")
    return path


@pytest.fixture
def client(data_file: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATA_FILE", str(data_file))
    # the with block runs the lifespan, which loads DATA_FILE
    with TestClient(app) as client:
        yield client
