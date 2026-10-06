import sqlite3

from api.db import SQLITE_DB_PATH, init_db
from api.privacy import apply_privacy, generate_deterministic_noise


def test_schema_has_no_event_coordinates():
    """
    Schema assertion: no persisted table contains raw event locations.
    Only cell centers (lat_c, lng_c) are stored.
    """
    init_db()
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    conn.close()

    forbidden_cols = ["event_lat", "event_lng", "raw_lat", "raw_lng", "exact_lat", "exact_lng"]
    table_names = [t[0] for t in tables]

    assert "demand_cells" in table_names
    assert "demand_daily" in table_names
    assert "ingest_batches" in table_names
    assert "rejected_summary" in table_names

    for name, sql in tables:
        sql_lower = sql.lower()
        for forbidden in forbidden_cols:
            assert forbidden not in sql_lower, f"Table {name} contains forbidden column {forbidden}"
        if name in ["ingest_batches", "rejected_summary"]:
            assert "lat" not in sql_lower
            assert "lng" not in sql_lower

def test_k_suppression():
    """
    Cells below K must never appear in responses.
    """
    cells = [
        {"h3": "88283082a1fffff", "count": 2},  # < 5, must be dropped
        {"h3": "88283082a3fffff", "count": 4},  # < 5, must be dropped
        {"h3": "88283082a5fffff", "count": 20}, # >= 5, kept
    ]
    # Test with epsilon=0 (deterministic no-noise test for pure K)
    res = apply_privacy(cells, from_ts="2026-09-01T00:00:00Z", to_ts="2026-09-02T00:00:00Z", k=5, epsilon=0.0)
    assert len(res) == 1
    assert res[0]["h3"] == "88283082a5fffff"
    assert res[0]["count"] == 20

def test_noise_is_deterministic():
    """
    Same (cell, window, category) must yield identical noise across multiple calls.
    """
    h3_cell = "8828308281fffff"
    w_start = "2026-09-01T00:00:00Z"
    w_end = "2026-09-02T00:00:00Z"
    cat = "food"

    n1 = generate_deterministic_noise(h3_cell, w_start, w_end, cat, epsilon=1.0)
    n2 = generate_deterministic_noise(h3_cell, w_start, w_end, cat, epsilon=1.0)
    assert n1 == n2, "Noise must be deterministic for identical parameters"

    # Differs when time window changes
    n3 = generate_deterministic_noise(h3_cell, "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z", cat, epsilon=1.0)
    assert n1 != n3, "Noise must vary across different time windows"

def test_threshold_applies_to_noisy_count():
    """
    Threshold K applies to the noisy value, not the raw value.
    If raw count is 4 but noise rounds it up to 5, it is kept.
    If raw count is 5 but noise rounds it down to 4, it is suppressed.
    """
    h3_cell = "8828308281fffff"
    w_start = "2026-09-01T00:00:00Z"
    w_end = "2026-09-02T00:00:00Z"
    noise = generate_deterministic_noise(h3_cell, w_start, w_end, None, epsilon=1.0)

    # Pick count such that count + noise < 5
    cells = [{"h3": h3_cell, "count": 5}]
    res = apply_privacy(cells, w_start, w_end, None, k=5, epsilon=1.0)

    noisy_expected = max(0, int(round(5 + noise)))
    if noisy_expected < 5:
        assert len(res) == 0, "Cell with noisy count < 5 must be suppressed"
    else:
        assert len(res) == 1
        assert res[0]["count"] == noisy_expected
