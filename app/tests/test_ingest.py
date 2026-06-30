"""Tests for the TMDB 5000 ingestion pipeline.

Building small synthetic CSV fixtures allows for
fast and deterministic E2E testing of the `ingest()` path
without loading the entire 5000-row dataset.
"""

import csv
import json
import sqlite3

import pytest

from app.ingest import _coerce_int, _coerce_float, ingest

MOVIE_FIELDS = [
    "budget",
    "genres",
    "id",
    "keywords",
    "original_language",
    "overview",
    "popularity",
    "release_date",
    "revenue",
    "runtime",
    "tagline",
    "title",
    "vote_average",
    "vote_count",
]
CREDIT_FIELDS = ["movie_id", "title", "cast", "crew"]


def _movie(id, title, release_date, genres=(), keywords=(), **overrides):
    row = {
        "budget": "100",
        "genres": json.dumps([{"name": g} for g in genres]),
        "id": str(id),
        "keywords": json.dumps([{"name": k} for k in keywords]),
        "original_language": "en",
        "overview": "An overview.",
        "popularity": "7.5",
        "release_date": release_date,
        "revenue": "200",
        "runtime": "139.0",
        "tagline": "A tagline.",
        "title": title,
        "vote_average": "8.0",
        "vote_count": "1000",
    }
    row.update(overrides)
    return row


def _credit(movie_id, title, cast=(), crew=()):
    return {
        "movie_id": str(movie_id),
        "title": title,
        "cast": json.dumps([{"name": n, "character": c} for n, c in cast]),
        "crew": json.dumps([{"name": n, "job": j} for n, j in crew]),
    }


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def dataset(tmp_path):
    """Two valid movies plus one undated (invalid) movie, written to temp CSVs.

    Returns:
        a (movies_path, credits_path, db_path) tuple ready for `ingest()`.
    """
    movies = [
        _movie(
            1,
            "The Tree of Life",
            "2011-05-27",
            genres=["Drama"],
            keywords=["existential"],
        ),
        _movie(2, "Stalker", "1979-05-25", genres=["Science Fiction", "Drama"]),
        _movie(3, "Undated Film", ""),  # missing release_date -> skipped
    ]
    credits = [
        _credit(
            1,
            "The Tree of Life",
            cast=[("Brad Pitt", "Mr. O'Brien"), ("Sean Penn", "Jack")],
            crew=[("Terrence Malick", "Director"), ("Editor X", "Editor")],
        ),
        _credit(
            2,
            "Stalker",
            cast=[("Alexander Kaidanovsky", "Stalker")],
            crew=[("Andrei Tarkovsky", "Director")],
        ),
        _credit(3, "Undated Film"),
    ]
    movies_path = tmp_path / "movies.csv"
    credits_path = tmp_path / "credits.csv"
    db_path = tmp_path / "movies.db"
    _write_csv(movies_path, MOVIE_FIELDS, movies)
    _write_csv(credits_path, CREDIT_FIELDS, credits)
    return movies_path, credits_path, db_path


def _counts(db_path):
    con = sqlite3.connect(db_path)
    try:
        return {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("movies", "genres", "keywords", "movie_cast", "crew")
        }
    finally:
        con.close()


@pytest.mark.parametrize(
    "value,expected",
    [("116.0", 116), ("116", 116), ("", None), ("0", 0)],
)
def test_coerce_int(value, expected):
    assert _coerce_int(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("7.5", 7.5), ("", None), ("0", 0.0)],
)
def test_coerce_float(value, expected):
    assert _coerce_float(value) == expected


def test_ingest_loads_expected_rows(dataset):
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)

    counts = _counts(db_path)
    assert counts["movies"] == 2  # undated movie skipped
    assert counts["genres"] == 3  # 1 + 2
    assert counts["movie_cast"] == 3  # 2 + 1
    assert counts["crew"] == 3  # 2 + 1


def test_ingest_skips_undated_movie(dataset):
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)

    con = sqlite3.connect(db_path)
    try:
        ids = {r[0] for r in con.execute("SELECT id FROM movies").fetchall()}
    finally:
        con.close()
    assert ids == {1, 2}  # id 3 (no release_date) absent


def test_movie_scalar_fields_are_coerced(dataset):
    """Scalar columns load and coerce correctly (year from release_date,
    runtime from a float-like string)."""
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        movie = con.execute("SELECT * FROM movies WHERE id = 1").fetchone()
        assert movie["title"] == "The Tree of Life"
        assert movie["year"] == 2011  # parsed from "2011-05-27"
        assert movie["runtime"] == 139  # coerced from "139.0"
    finally:
        con.close()


def test_director_is_extracted_from_crew(dataset):
    """The director is identified by filtering crew on job = 'Director'."""
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)

    con = sqlite3.connect(db_path)
    try:
        director = con.execute(
            "SELECT name FROM crew WHERE movie_id = 1 AND job = 'Director'"
        ).fetchone()
    finally:
        con.close()
    assert director[0] == "Terrence Malick"


def test_genres_are_linked_to_movie(dataset):
    """A movie's genres are stored as one row per genre, linked by movie_id."""
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)

    con = sqlite3.connect(db_path)
    try:
        genres = {
            r[0] for r in con.execute("SELECT name FROM genres WHERE movie_id = 2")
        }
    finally:
        con.close()
    assert genres == {"Science Fiction", "Drama"}


def test_ingest_is_idempotent(dataset):
    """Re-ingesting without --overwrite must not duplicate child rows."""
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)
    first = _counts(db_path)
    ingest(movies_path, credits_path, db_path)
    second = _counts(db_path)
    assert first == second


def test_delete_movie_cascades(dataset):
    """ON DELETE CASCADE removes a movie's child rows when FKs are enforced."""
    movies_path, credits_path, db_path = dataset
    ingest(movies_path, credits_path, db_path)

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        con.execute("DELETE FROM movies WHERE id = 1")
        con.commit()
        for table in ("genres", "keywords", "movie_cast", "crew"):
            remaining = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE movie_id = 1"
            ).fetchone()[0]
            assert remaining == 0, f"{table} not cascaded"
    finally:
        con.close()
