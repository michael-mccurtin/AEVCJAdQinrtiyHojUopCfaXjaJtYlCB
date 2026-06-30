import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

# Defence-in-depth: if the generated SQL omits a LIMIT, bound the result set
# so a broad query (e.g. "all movies ever released) can't return the entire table.
MAX_ROWS = 50


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a read-only SQLite connection. Prevents any write operations at the driver level.

    db_path defaults to the configured database; it is parameterised so callers and tests can target an alternate file.
    """
    db_path = db_path or settings.db_path
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _ensure_limit(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Append a LIMIT clause when the query has none, leaving an explicit one intact."""
    if re.search(r"\blimit\b", sql, re.IGNORECASE):
        return sql
    return f"{sql.rstrip().rstrip(';')} LIMIT {max_rows}"


def execute_query(sql: str, db_path: Path | None = None) -> list[dict]:
    """Execute a read-only SQL query and return results as a list of dicts.

    Wraps the connection in closing() as sqlite3 connection's context
    manager only commits/rolls back the transaction (without closing the handle)
    """
    sql = _ensure_limit(sql)
    with closing(get_connection(db_path)) as con:
        try:
            rows = con.execute(sql).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            log.error("SQL execution failed: %s\nQuery: %s", e, sql)
            raise
