"""Create the table places in PostGIS and load a GeoNames file (from session 8).

The same steps as 06-postgis/load-cities.sh of cloud-labs-local, but in Python
and inside the image: the image already contains the GeoNames file
(DATA_FILE). A service whose database sits in a private network, unreachable
from the own computer, can therefore load its data itself:

- placefinder-load [--replace] [file]: load once, e.g. as a job or by hand
  with docker compose exec api placefinder-load
- DATABASE_INIT=true: PlaceFinder loads the file at startup if the table
  places does not exist yet (main.py)

An advisory lock makes sure that only one process loads, even if several
instances start at the same time; the others wait and then find the table.
Table, data and indexes are created in one transaction: a failed load leaves
nothing behind.

In production, the schema belongs to versioned migrations (e.g. Alembic) that
a pipeline runs once before the new version starts.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import psycopg

from placefinder.db import describe

logger = logging.getLogger("uvicorn.error")

# as 06-postgis/schema.sql of cloud-labs-local
SCHEMA = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
DROP TABLE IF EXISTS places;
CREATE TABLE places (
    geonameid         integer PRIMARY KEY,
    name              text NOT NULL,
    asciiname         text,
    alternatenames    text,
    latitude          double precision NOT NULL,
    longitude         double precision NOT NULL,
    feature_class     char(1),
    feature_code      text,
    country_code      char(2),
    cc2               text,
    admin1_code       text,
    admin2_code       text,
    admin3_code       text,
    admin4_code       text,
    population        bigint,
    elevation         integer,
    dem               integer,
    timezone          text,
    modification_date date
)"""

# CSV with a tab delimiter turns empty fields into NULL; the quote character
# \x01 never occurs in the data
COPY = "COPY places FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01')"

# as 06-postgis/indexes.sql of cloud-labs-local; the last index must match
# ALL_NAMES in db.py
INDEXES = """
ALTER TABLE places ADD COLUMN geom geography(Point, 4326)
  GENERATED ALWAYS AS (ST_MakePoint(longitude, latitude)::geography) STORED;
CREATE INDEX places_geom_idx ON places USING gist (geom);
CREATE INDEX places_name_trgm_idx ON places USING gin (name gin_trgm_ops);
CREATE INDEX places_all_names_trgm_idx ON places USING gin ((
  ',' || lower(name) || ',' || lower(coalesce(asciiname, '')) || ','
  || lower(coalesce(alternatenames, '')) || ',') gin_trgm_ops)"""

# any number that no other part of the application uses as a lock
LOCK_ID = 2929670


def load(conninfo: str, path: Path, replace: bool = False) -> int:
    """Load the GeoNames file into the table places; returns the number of
    places, or 0 if the table exists and replace is False."""
    start = time.perf_counter()
    with psycopg.connect(conninfo, connect_timeout=10) as conn:
        # released at the end of the transaction
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        exists = conn.execute("SELECT to_regclass('places') IS NOT NULL").fetchone()
        if exists and exists[0] and not replace:
            return 0
        conn.execute(SCHEMA)
        with conn.cursor() as cur, cur.copy(COPY) as copy, path.open("rb") as file:
            while chunk := file.read(1 << 20):
                copy.write(chunk)
        conn.execute(INDEXES)
        count = conn.execute("SELECT count(*) FROM places").fetchone()
        # commit before ANALYZE: it should see the finished table
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("ANALYZE places")
    places = count[0] if count else 0
    logger.info(
        "Loaded %d places from %s into %s in %.1f s",
        places,
        path,
        describe(conninfo),
        time.perf_counter() - start,
    )
    return places


def main() -> None:
    """Command placefinder-load."""
    parser = argparse.ArgumentParser(
        description="Load a GeoNames file into the table places of DATABASE_URL."
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=Path(os.environ.get("DATA_FILE", "")),
        help="GeoNames text file (default: DATA_FILE)",
    )
    parser.add_argument(
        "--replace", action="store_true", help="drop and reload the table if it exists"
    )
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    if not args.file.is_file():
        sys.exit(f"GeoNames file {args.file} not found. Give a file or set DATA_FILE.")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if load(url, args.file, args.replace) == 0:
        logger.info("Table places exists already; use --replace to load it again.")


if __name__ == "__main__":
    main()
