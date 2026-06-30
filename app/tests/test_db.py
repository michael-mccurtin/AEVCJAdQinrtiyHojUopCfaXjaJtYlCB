"""Tests for the read-only query layer: helpers, read-only enforcement, and results."""

import sqlite3
from contextlib import closing

import pytest

from app.db.db import MAX_ROWS, _ensure_limit, execute_query, get_connection


@pytest.fixture
def db(tmp_path):
    """Small SQLite DB with 60 movies (> MAX_ROWS) for query-layer tests."""
    path = tmp_path / "movies.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE movies (id INTEGER PRIMARY KEY, title TEXT)")
    con.executemany(
        "INSERT INTO movies (id, title) VALUES (?, ?)",
        [(i, f"Movie {i}") for i in range(1, 61)],
    )
    con.commit()
    con.close()
    return path


def test_ensure_limit_appended_when_missing():
    assert (
        _ensure_limit("SELECT id FROM movies")
        == f"SELECT id FROM movies LIMIT {MAX_ROWS}"
    )


def test_ensure_limit_strips_trailing_semicolon():
    assert (
        _ensure_limit("SELECT id FROM movies;")
        == f"SELECT id FROM movies LIMIT {MAX_ROWS}"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM movies LIMIT 10",
        "SELECT id FROM movies limit 5",  # case-insensitive
    ],
)
def test_ensure_limit_leaves_explicit_limit_untouched(sql):
    assert _ensure_limit(sql) == sql


def test_get_connection_is_read_only(db):
    """Security boundary: writes are rejected at the driver level."""
    with closing(get_connection(db)) as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO movies (id, title) VALUES (999, 'x')")


def test_execute_query_returns_list_of_dicts(db):
    rows = execute_query("SELECT id, title FROM movies WHERE id = 1", db_path=db)
    assert rows == [{"id": 1, "title": "Movie 1"}]


def test_execute_query_caps_unbounded_results(db):
    """A SELECT with no LIMIT is bounded to MAX_ROWS, not the full 60 rows."""
    rows = execute_query("SELECT id FROM movies", db_path=db)
    assert len(rows) == MAX_ROWS
