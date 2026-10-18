"""Places in PostgreSQL with PostGIS (from session 6).

The table places holds the 19 columns of a GeoNames dump, a generated column
geom geography(Point, 4326) with a GiST index and trigram indexes on name and
on all names (ALL_NAMES). t06-datenbank/load-cities.sh of the lab repositories
creates and loads it, locally (service db in compose.yaml) or at a cloud
provider.

All values reach the server as parameters (%(name)s), separately from the SQL
text. The f-strings below only combine fixed pieces of SQL, never input.
"""

from typing import Any

import psycopg
from psycopg import errors
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from placefinder.repository import Hit, Place, SearchQuery

COLUMNS = """geonameid, name, latitude, longitude, country_code,
       coalesce(population, 0) AS population, coalesce(feature_code, '') AS feature_code,
       coalesce(timezone, '') AS timezone"""

# all names of a place in lower case, each followed by a comma, e.g.
# ",erfurt,erfurt,erf,erfordia,ehrfurt,". A name starts with q if this text
# is LIKE '%,q%'. The expression is the same as in the index
# places_all_names_trgm_idx (t06-datenbank/indexes.sql), so the search uses it.
ALL_NAMES = (
    "(',' || lower(name) || ',' || lower(coalesce(asciiname, '')) || ','"
    " || lower(coalesce(alternatenames, '')) || ',')"
)

# sort keys per sort order, the id last so that every key is unique; equal
# populations in descending order of the id: ORDER BY population DESC, id DESC
KEYS = {
    "relevance": ["rank", "-population", "-geonameid"],
    "-population": ["-population", "-geonameid"],
    "name": ["lower(name)", "geonameid"],
    "distance": ["round(distance::numeric, 1)::float8", "geonameid"],
}


def escape_like(text: str) -> str:
    """Escape the wildcards of LIKE, so that q matches literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def describe(conninfo: str) -> str:
    """Host and database of a connection string, without user and password."""
    info = conninfo_to_dict(conninfo)
    return f"{info.get('host', 'localhost')}:{info.get('port', 5432)}/{info.get('dbname', '')}"


class PostgisRepository:
    """Place store in PostgreSQL with PostGIS, see Repository in repository.py."""

    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo
        # a few connections, reused by all requests; opened and closed in the
        # lifespan of the app (main.py)
        self.pool = ConnectionPool(
            conninfo, open=False, min_size=1, max_size=4, kwargs={"row_factory": dict_row}
        )

    def open(self) -> None:
        """Check the database with one connection, then open the pool."""
        # the single connection fails at once and says why (not reachable,
        # wrong password, no database); the pool would retry for 30 seconds
        with psycopg.connect(self.conninfo, connect_timeout=10) as conn:
            try:
                conn.execute("SELECT 'places'::regclass")
            except errors.UndefinedTable:
                raise RuntimeError(
                    "Table places not found. Load it with t06-datenbank/load-cities.sh."
                ) from None
        self.pool.open(wait=True, timeout=30)

    def close(self) -> None:
        self.pool.close()

    def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def count(self) -> int:
        # the estimate of the planner: a count(*) would read the whole table on
        # every health check; ANALYZE after loading makes it exact
        rows = self._rows(
            "SELECT greatest(reltuples, 0)::bigint AS n FROM pg_class "
            "WHERE oid = 'places'::regclass",
            {},
        )
        return rows[0]["n"]

    def get(self, place_id: int) -> Place | None:
        rows = self._rows(
            f"SELECT {COLUMNS} FROM places WHERE geonameid = %(id)s", {"id": place_id}
        )
        return to_place(rows[0]) if rows else None

    def find(self, query: SearchQuery) -> list[Hit]:
        where = ["TRUE"]
        params: dict[str, Any] = {"limit": query.limit + 1}
        rank = "0"
        distance = "NULL::float8"
        if query.q is not None:
            q = query.q.strip().lower()
            if not q or "\x00" in q:  # PostgreSQL text never contains NUL
                return []
            # rank 0 if a name equals q, 1 if a name only starts with q
            pattern = "%," + escape_like(q)
            params |= {"prefix": pattern + "%", "exact": pattern + ",%"}
            where.append(f"{ALL_NAMES} LIKE %(prefix)s")  # uses the trigram index
            rank = f"CASE WHEN {ALL_NAMES} LIKE %(exact)s THEN 0 ELSE 1 END"
        if query.near:
            lon, lat, radius = query.near
            params |= {"lon": lon, "lat": lat, "radius": radius}
            point = "ST_MakePoint(%(lon)s, %(lat)s)::geography"
            where.append(f"ST_DWithin(geom, {point}, %(radius)s)")  # uses the GiST index
            distance = f"ST_Distance(geom, {point})"
        if query.bbox:
            # a box in degrees: longitude and latitude directly. On geography,
            # the edges of the box would be great circles, not parallels.
            params |= dict(query.bbox._asdict())
            where.append(
                "longitude BETWEEN %(min_lon)s AND %(max_lon)s "
                "AND latitude BETWEEN %(min_lat)s AND %(max_lat)s"
            )
        if query.country:
            params["country"] = query.country
            where.append("country_code = %(country)s")

        keys = KEYS[query.sort]
        key_columns = ", ".join(f"{expr} AS k{i}" for i, expr in enumerate(keys))
        key_names = ", ".join(f"k{i}" for i in range(len(keys)))
        after = "TRUE"
        if query.after is not None:
            # keyset pagination: row comparison with the key of the last place
            params |= {f"a{i}": value for i, value in enumerate(query.after)}
            after = f"({key_names}) > ({', '.join(f'%(a{i})s' for i in range(len(keys)))})"
        sql = f"""
            SELECT * FROM (
                SELECT *, {key_columns} FROM (
                    SELECT {COLUMNS}, {rank} AS rank, {distance} AS distance
                    FROM places
                    WHERE {" AND ".join(where)}
                ) AS found
            ) AS keyed
            WHERE {after}
            ORDER BY {key_names}
            LIMIT %(limit)s"""
        return [
            Hit(
                to_place(row),
                row["distance"],
                tuple(row[f"k{i}"] for i in range(len(keys))),
            )
            for row in self._rows(sql, params)
        ]


def to_place(row: dict[str, Any]) -> Place:
    return Place(
        id=row["geonameid"],
        name=row["name"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        country_code=row["country_code"],
        population=row["population"],
        feature_code=row["feature_code"],
        timezone=row["timezone"],
    )
