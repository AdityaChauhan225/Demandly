import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from api.config import DATABASE_URL

logger = logging.getLogger(__name__)

# Check if using SQLite or PostgreSQL
IS_SQLITE = DATABASE_URL.startswith("sqlite")
SQLITE_DB_PATH = DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", "") if IS_SQLITE else (
    "demandly.db" if Path("demandly.db").exists() else "geodemand.db"
)

_pg_pool = None

def get_pg_pool():
    global _pg_pool
    if _pg_pool is None and not IS_SQLITE:
        try:
            from psycopg_pool import ConnectionPool
            _pg_pool = ConnectionPool(
                conninfo=DATABASE_URL,
                min_size=1,
                max_size=10,
                timeout=5.0
            )
            _pg_pool.open()
            logger.info("Connected to PostgreSQL via psycopg_pool")
        except Exception as e:
            logger.warning(f"Failed to connect to PostgreSQL: {e}. Will attempt SQLite fallback.")
            _pg_pool = None
    return _pg_pool

def get_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(schema_path: str | None = None):
    """
    Initialises the database tables and indexes from schema.sql.
    """
    if schema_path is None:
        schema_path = str(Path(__file__).resolve().parent.parent / "sql" / "schema.sql")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    pool = get_pg_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
                conn.commit()
            logger.info("Initialized PostgreSQL schema")
            return
        except Exception as e:
            logger.warning(f"Postgres schema init error: {e}. Falling back to SQLite.")

    # SQLite initialization
    sqlite_conn = get_sqlite_conn()
    try:
        # SQLite schema adaptation
        sqlite_schema = schema_sql.replace("TIMESTAMPTZ", "TEXT")
        sqlite_schema = sqlite_schema.replace("DOUBLE PRECISION", "REAL")
        sqlite_schema = sqlite_schema.replace("CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP")
        sqlite_conn.executescript(sqlite_schema)
        sqlite_conn.commit()
        logger.info(f"Initialized SQLite database at {SQLITE_DB_PATH}")
    finally:
        sqlite_conn.close()

def execute_query(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Executes a read query across PostgreSQL or SQLite with dictionary results.
    """
    pool = get_pg_pool()
    if pool is not None:
        try:
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute(query, params)
                cols = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()
                return [dict(zip(cols, row)) for row in rows]
        except Exception as e:
            logger.warning(f"PostgreSQL query failed ({e}), falling back to SQLite if available")

    # Fallback / Direct SQLite execution
    sqlite_conn = get_sqlite_conn()
    try:
        # Translate %(param)s to :param for SQLite
        sqlite_query = re.sub(r'%\((\w+)\)s', r':\1', query)
        # Format datetimes to ISO strings for SQLite
        formatted_params = {}
        for k, v in params.items():
            if isinstance(v, datetime):
                formatted_params[k] = v.isoformat()
            else:
                formatted_params[k] = v
        cur = sqlite_conn.cursor()
        cur.execute(sqlite_query, formatted_params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        sqlite_conn.close()

def get_cells(
    source_table: str,
    res: int,
    from_dt: datetime,
    to_dt: datetime,
    w: float,
    s: float,
    e: float,
    n: float,
    category: str | None = None
) -> list[dict[str, Any]]:
    """
    Queries aggregated counts per H3 cell within bounding box and time range.
    """
    cat_filter = "AND category = %(cat)s" if category else ""
    query = f"""
    SELECT h3, CAST(SUM(cnt) AS INTEGER) AS count
    FROM {source_table}
    WHERE res = %(res)s
      AND bucket >= %(from)s AND bucket < %(to)s
      AND lat_c BETWEEN %(s)s AND %(n)s
      AND lng_c BETWEEN %(w)s AND %(e)s
      {cat_filter}
    GROUP BY h3
    """
    params: dict[str, Any] = {
        "res": res,
        "from": from_dt.isoformat() if isinstance(from_dt, datetime) else str(from_dt),
        "to": to_dt.isoformat() if isinstance(to_dt, datetime) else str(to_dt),
        "s": s,
        "n": n,
        "w": w,
        "e": e,
    }
    if category:
        params["cat"] = category

    return execute_query(query, params)

def get_top_zones(
    source_table: str,
    res: int,
    from_dt: datetime,
    to_dt: datetime,
    prev_from_dt: datetime,
    category: str | None = None,
    limit: int = 10,
    overfetch: int = 30
) -> list[dict[str, Any]]:
    """
    Queries ranked zones comparing current window against previous window.
    Uses CASE-based aggregation for universal SQL compatibility.
    """
    cat_filter = "AND category = %(cat)s" if category else ""
    from_str = from_dt.isoformat() if isinstance(from_dt, datetime) else str(from_dt)
    to_str = to_dt.isoformat() if isinstance(to_dt, datetime) else str(to_dt)
    prev_from_str = prev_from_dt.isoformat() if isinstance(prev_from_dt, datetime) else str(prev_from_dt)

    query = f"""
    SELECT
      h3,
      MIN(lat_c) AS lat_c,
      MIN(lng_c) AS lng_c,
      CAST(COALESCE(SUM(CASE WHEN bucket >= %(from)s THEN cnt ELSE 0 END), 0) AS INTEGER) AS cur,
      CAST(COALESCE(SUM(CASE WHEN bucket < %(from)s THEN cnt ELSE 0 END), 0) AS INTEGER) AS prev
    FROM {source_table}
    WHERE res = %(res)s
      AND bucket >= %(prev_from)s AND bucket < %(to)s
      {cat_filter}
    GROUP BY h3
    ORDER BY cur DESC
    LIMIT %(overfetch)s
    """
    params: dict[str, Any] = {
        "res": res,
        "from": from_str,
        "to": to_str,
        "prev_from": prev_from_str,
        "overfetch": overfetch
    }
    if category:
        params["cat"] = category

    rows = execute_query(query, params)
    result = []
    for r in rows:
        result.append({
            "h3": r["h3"],
            "center": (round(float(r["lat_c"]), 5), round(float(r["lng_c"]), 5)),
            "count": int(r["cur"]),
            "previous": int(r["prev"])
        })
    return result

def get_zone_hourly(
    h3_cell: str,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    category: str | None = None
) -> dict[str, Any]:
    """
    Calculates hour-of-day profile (0-23) for a specific H3 cell across hourly buckets.
    """
    time_filter = ""
    params: dict[str, Any] = {"h3": h3_cell}

    if from_dt and to_dt:
        time_filter += " AND bucket >= %(from)s AND bucket < %(to)s"
        params["from"] = from_dt.isoformat() if isinstance(from_dt, datetime) else str(from_dt)
        params["to"] = to_dt.isoformat() if isinstance(to_dt, datetime) else str(to_dt)

    if category:
        time_filter += " AND category = %(cat)s"
        params["cat"] = category

    # We fetch bucket and cnt to compute hour-of-day in python or SQL
    query = f"""
    SELECT bucket, cnt
    FROM demand_cells
    WHERE h3 = %(h3)s {time_filter}
    """
    rows = execute_query(query, params)

    hourly_counts = {h: 0 for h in range(24)}
    for r in rows:
        b = r["bucket"]
        if isinstance(b, str):
            # Parse ISO or SQLite string
            dt = datetime.fromisoformat(b.replace("Z", "+00:00"))
        else:
            dt = b
        h = dt.hour
        hourly_counts[h] += int(r["cnt"])

    # Determine peak hours (top 2 hours with non-zero counts)
    sorted_hours = sorted(hourly_counts.items(), key=lambda x: x[1], reverse=True)
    peak_hours = [h for h, cnt in sorted_hours[:2] if cnt > 0]
    peak_hours.sort()

    hours_list = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]
    return {
        "h3": h3_cell,
        "hours": hours_list,
        "peak_hours": peak_hours
    }

def get_meta_info() -> dict[str, Any]:
    """
    Returns metadata for dashboard initialization.
    """
    # Categories
    cat_query = "SELECT DISTINCT category FROM demand_cells ORDER BY category"
    cat_rows = execute_query(cat_query, {})
    categories = [r["category"] for r in cat_rows]

    # Time range and counts
    stats_query = """
    SELECT
      MIN(bucket) AS min_b,
      MAX(bucket) AS max_b,
      COUNT(*) AS total_cells,
      COALESCE(SUM(cnt), 0) AS total_events
    FROM demand_cells
    WHERE res = 8
    """
    stats_rows = execute_query(stats_query, {})
    stats = stats_rows[0] if stats_rows else {}

    min_b = stats.get("min_b")
    max_b = stats.get("max_b")

    min_str = min_b.isoformat() if isinstance(min_b, datetime) else (str(min_b) if min_b else None)
    max_str = max_b.isoformat() if isinstance(max_b, datetime) else (str(max_b) if max_b else None)

    return {
        "categories": categories if categories else ["food", "cab", "grocery", "pharmacy"],
        "time_range": {
            "from": min_str,
            "to": max_str
        },
        "total_cells": int(stats.get("total_cells") or 0),
        "total_events": int(stats.get("total_events") or 0)
    }

def check_db_health() -> bool:
    try:
        rows = execute_query("SELECT 1 AS ok", {})
        return len(rows) > 0 and rows[0].get("ok") == 1
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        return False
