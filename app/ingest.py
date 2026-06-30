"""
Load TMDB 5000 dataset into SQLite.

Usage:
    uv run python -m app.ingest
    uv run python -m app.ingest --movies data/tmdb_5000/tmdb_5000_movies.csv \
                                --credits data/tmdb_5000/tmdb_5000_credits.csv
    uv run python -m app.ingest --overwrite
"""

import argparse
import csv
import json
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

DEFAULT_MOVIES_PATH = Path("data/tmdb_5000/tmdb_5000_movies.csv")
DEFAULT_CREDITS_PATH = Path("data/tmdb_5000/tmdb_5000_credits.csv")
SCHEMA_PATH = Path("app/db/schema.sql")


def _coerce_int(val: str) -> int | None:
    """Coerce a CSV numeric string to int, returning None for empty values.

    TMDB CSV stores numeric fields like runtime as "116.0" rather than "116".
    int() rejects decimal strings, so float() is used first.
    """
    return int(float(val)) if val else None


def _coerce_float(val: str) -> float | None:
    """Coerce a CSV numeric string to float, returning None for empty values."""
    return float(val) if val else None


def _init_db(con: sqlite3.Connection, overwrite: bool) -> None:
    """Initialise the database schema, optionally wiping existing data first.

    Args:
        con: Open SQLite connection.
        overwrite: If True, drop all tables before recreating them. Use this
            when re-ingesting after a schema change.
    """
    if overwrite:
        con.executescript("""
            DROP TABLE IF EXISTS crew;
            DROP TABLE IF EXISTS movie_cast;
            DROP TABLE IF EXISTS keywords;
            DROP TABLE IF EXISTS genres;
            DROP TABLE IF EXISTS movies;
        """)
    con.executescript(SCHEMA_PATH.read_text())


def _load_credits(credits_path: Path) -> dict[str, dict]:
    """Load the credits CSV into a dict keyed by movie_id.

    Holding all credits in memory enables O(1) lookup of cast/crew for each movie,
    rather than re-scanning the file for every row.

    Args:
        credits_path: Path to tmdb_5000_credits.csv.
    """
    with open(credits_path, newline="") as f:
        return {row["movie_id"]: row for row in csv.DictReader(f)}


def _insert_movie(con: sqlite3.Connection, row: dict) -> int:
    """Insert a single movie row and return its id.

    Args:
        con: Open SQLite connection.
        row: Raw CSV row dict from tmdb_5000_movies.csv.

    Returns:
        The movie's integer id.

    Raises:
        ValueError: If release_date is missing. Treating undated movies as
            unfit for ingestion, since year is a core filter field.
    """
    if not row["release_date"]:
        raise ValueError(f"missing release_date for movie {row['title']!r}")

    movie_id = int(row["id"])
    year = int(row["release_date"][:4])

    con.execute(
        """
        INSERT OR REPLACE INTO movies
            (id, title, year, overview, tagline, runtime, budget,
             revenue, vote_average, vote_count, popularity, original_language)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            movie_id,
            row["title"],
            year,
            row["overview"] or None,
            row["tagline"] or None,
            _coerce_int(row["runtime"]),
            _coerce_int(row["budget"]),
            _coerce_int(row["revenue"]),
            _coerce_float(row["vote_average"]),
            _coerce_int(row["vote_count"]),
            _coerce_float(row["popularity"]),
            row["original_language"] or None,
        ),
    )
    return movie_id


def _insert_genres_and_keywords(
    con: sqlite3.Connection, movie_id: int, row: dict, replace: bool = True
) -> None:
    """Insert genre and keyword rows for a movie.

    Args:
        con: Open SQLite connection.
        movie_id: The movie's integer id.
        row: Raw CSV row dict containing JSON-encoded genres and keywords columns.
        replace: If True, delete this movie's existing rows first so re-ingesting
            stays idempotent. Skipped on a clean (overwrite) load, where the
            tables start empty and the deletes are pure no-ops.
    """
    if replace:
        con.execute("DELETE FROM genres WHERE movie_id = ?", (movie_id,))
        con.execute("DELETE FROM keywords WHERE movie_id = ?", (movie_id,))

    for genre in json.loads(row["genres"] or "[]"):
        con.execute(
            "INSERT INTO genres (movie_id, name) VALUES (?,?)",
            (movie_id, genre["name"]),
        )

    for keyword in json.loads(row["keywords"] or "[]"):
        con.execute(
            "INSERT INTO keywords (movie_id, keyword) VALUES (?,?)",
            (movie_id, keyword["name"]),
        )


def _insert_cast_and_crew(
    con: sqlite3.Connection, movie_id: int, credit: dict, replace: bool = True
) -> None:
    """Insert cast and crew rows for a movie.

    Args:
        con: Open SQLite connection.
        movie_id: The movie's integer id.
        credit: Raw credits CSV row dict for this movie, or an empty dict if
            no credits were found.
        replace: If True, delete this movie's existing rows first so re-ingesting
            stays idempotent. Skipped on a clean (overwrite) load, where the
            tables start empty and the deletes are pure no-ops.
    """
    if replace:
        con.execute("DELETE FROM movie_cast WHERE movie_id = ?", (movie_id,))
        con.execute("DELETE FROM crew WHERE movie_id = ?", (movie_id,))

    for i, cast_member in enumerate(json.loads(credit.get("cast", "[]"))):
        con.execute(
            "INSERT INTO movie_cast (movie_id, name, character, cast_order) VALUES (?,?,?,?)",
            (movie_id, cast_member["name"], cast_member.get("character"), i),
        )

    for crew_member in json.loads(credit.get("crew", "[]")):
        con.execute(
            "INSERT INTO crew (movie_id, name, job) VALUES (?,?,?)",
            (movie_id, crew_member["name"], crew_member["job"]),
        )


def ingest(
    movies_path: Path, credits_path: Path, db_path: Path, overwrite: bool = False
) -> None:
    """Load the TMDB 5000 dataset into a local SQLite database.

    Reads two CSVs (movies and credits), joins them on movie_id, and writes
    normalised rows into movies, genres, keywords, cast, and crew tables.
    Bad rows are skipped with a warning rather than aborting the run.

    Args:
        movies_path: Path to tmdb_5000_movies.csv.
        credits_path: Path to tmdb_5000_credits.csv.
        db_path: Destination SQLite database file (created if absent).
        overwrite: Drop and recreate all tables before ingesting.
    """
    start = time.monotonic()
    movie_count = 0

    # isolation_level=None puts the driver in autocommit mode so we manage the
    # transaction explicitly: the entire load runs inside a single transaction,
    # with a per-movie savepoint nested inside it for
    # cheap, in-memory rollback of any malformed row.
    with closing(sqlite3.connect(db_path, isolation_level=None)) as con:
        _init_db(con, overwrite)
        # Enforce foreign keys for the load phase only. Doing this before
        # _init_db would make dropping the parent `movies` table fail while
        # child tables still reference it.
        con.execute("PRAGMA foreign_keys = ON")

        credits = _load_credits(credits_path)

        # On a clean overwrite the tables are empty, so the per-movie
        # delete-before-insert is redundant and can be skipped.
        replace = not overwrite

        con.execute("BEGIN")
        with open(movies_path, newline="") as f:
            for row in csv.DictReader(f):
                con.execute("SAVEPOINT movie")
                try:
                    movie_id = _insert_movie(con, row)
                    _insert_genres_and_keywords(con, movie_id, row, replace)
                    _insert_cast_and_crew(
                        con, movie_id, credits.get(str(movie_id), {}), replace
                    )
                    con.execute("RELEASE movie")
                    movie_count += 1
                except Exception as e:
                    con.execute("ROLLBACK TO movie")
                    con.execute("RELEASE movie")
                    log.warning(
                        "Skipping movie %r (ID %s): %s",
                        row.get("title"),
                        row.get("id"),
                        e,
                    )
        con.execute("COMMIT")

    log.info(
        "Ingested %d movies into %s in %.1fs",
        movie_count,
        db_path,
        time.monotonic() - start,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--movies", type=Path, default=DEFAULT_MOVIES_PATH)
    parser.add_argument("--credits", type=Path, default=DEFAULT_CREDITS_PATH)
    parser.add_argument("--db", type=Path, default=settings.db_path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    ingest(args.movies, args.credits, args.db, args.overwrite)


if __name__ == "__main__":
    main()
