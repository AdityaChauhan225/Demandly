import sqlite3
import time
from typing import Any

import h3
import pandas as pd


def setup_baseline_raw_table(events_df: pd.DataFrame, db_path: str = "bench_raw.db") -> sqlite3.Connection:
    """
    Creates a benchmark-only raw events database (B0) where raw lat/lng are stored.
    This database is strictly for benchmark comparison against the pre-aggregated design.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS raw_events")
    cur.execute("""
        CREATE TABLE raw_events (
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            ts TEXT NOT NULL,
            category TEXT NOT NULL
        )
    """)
    records = [
        (float(r["lat"]), float(r["lng"]), str(r["ts"]), str(r["category"]))
        for _, r in events_df.iterrows()
    ]
    cur.executemany("INSERT INTO raw_events VALUES (?, ?, ?, ?)", records)
    conn.commit()
    return conn

def execute_b0_raw_query(
    conn: sqlite3.Connection,
    w: float,
    s: float,
    e: float,
    n: float,
    from_iso: str,
    to_iso: str,
    res: int = 8
) -> dict[str, Any]:
    """
    B0 Baseline query: Scans raw events table, filters by bbox and time range,
    and performs on-the-fly H3 hexagon bucketing in Python/memory.
    """
    start = time.perf_counter()
    cur = conn.cursor()
    query = """
        SELECT lat, lng, category
        FROM raw_events
        WHERE lat BETWEEN ? AND ?
          AND lng BETWEEN ? AND ?
          AND ts >= ? AND ts < ?
    """
    cur.execute(query, (s, n, w, e, from_iso, to_iso))
    rows = cur.fetchall()

    # On-the-fly H3 conversion and aggregation
    counts: dict[str, int] = {}
    for lat, lng, _ in rows:
        cell = h3.latlng_to_cell(lat, lng, res)
        counts[cell] = counts.get(cell, 0) + 1

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "elapsed_ms": elapsed_ms,
        "rows_scanned": len(rows),
        "unique_cells": len(counts),
        "counts": counts
    }
