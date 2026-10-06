from datetime import datetime, timezone

import pandas as pd

from api.db import execute_query, init_db
from ingest.load import load_batch
from ingest.transform import transform_events_to_cells
from ingest.validate import validate_events


def test_validation_rejection_reasons():
    raw_data = [
        # 1. Valid event
        {"lat": 12.97, "lng": 77.59, "ts": "2026-09-01T12:00:00Z", "category": "food"},
        # 2. Missing coordinate
        {"lat": None, "lng": 77.59, "ts": "2026-09-01T12:00:00Z", "category": "food"},
        # 3. Null island
        {"lat": 0.0, "lng": 0.0, "ts": "2026-09-01T12:00:00Z", "category": "food"},
        # 4. Bad coordinates (out of range)
        {"lat": 95.0, "lng": 77.59, "ts": "2026-09-01T12:00:00Z", "category": "food"},
        # 5. Bad timestamp
        {"lat": 12.97, "lng": 77.59, "ts": "not-a-valid-date", "category": "food"},
        # 6. Timestamp out of range (too old)
        {"lat": 12.97, "lng": 77.59, "ts": "2015-01-01T00:00:00Z", "category": "food"},
        # 7. Bad category
        {"lat": 12.97, "lng": 77.59, "ts": "2026-09-01T12:00:00Z", "category": "unknown_cat"},
    ]
    df = pd.DataFrame(raw_data)
    valid_df, reasons = validate_events(df)

    assert len(valid_df) == 1
    assert reasons["missing_coord"] == 1
    assert reasons["null_island"] == 1
    assert reasons["bad_coord"] == 1
    assert reasons["bad_ts"] == 1
    assert reasons["ts_out_of_range"] == 1
    assert reasons["bad_category"] == 1

def test_transform_drops_coordinates():
    valid_data = [
        {"lat": 12.97, "lng": 77.59, "ts": "2026-09-01T12:15:00Z", "category": "food"},
        {"lat": 12.97, "lng": 77.59, "ts": "2026-09-01T12:45:00Z", "category": "food"},
    ]
    df = pd.DataFrame(valid_data)
    valid_df, _ = validate_events(df)
    transformed = transform_events_to_cells(valid_df)

    # Check columns
    assert "lat" not in transformed.columns
    assert "lng" not in transformed.columns
    assert set(transformed["res"].unique()) == {6, 7, 8, 9}

    # Hourly grouping: 2 events in the same hour and cell must aggregate to cnt=2
    res9 = transformed[transformed["res"] == 9]
    assert len(res9) == 1
    assert res9.iloc[0]["cnt"] == 2

def test_idempotent_ingest_and_additive_updates():
    init_db()
    batch_id = f"test-batch-{datetime.now(timezone.utc).timestamp()}"

    valid_data = [
        {"lat": 12.97, "lng": 77.59, "ts": "2026-09-01T12:10:00Z", "category": "food"},
        {"lat": 12.97, "lng": 77.59, "ts": "2026-09-01T12:20:00Z", "category": "food"},
    ]
    df = pd.DataFrame(valid_data)
    valid_df, reasons = validate_events(df)
    transformed = transform_events_to_cells(valid_df)

    # 1. First ingest
    r1 = load_batch(batch_id, transformed, events_in=2, accepted=2, rejected=0, rejection_reasons=reasons)
    assert r1["duplicate_batch"] is False
    assert r1["accepted"] == 2

    # Verify rows in DB
    rows = execute_query("SELECT SUM(cnt) as total FROM demand_cells WHERE res = 9", {})
    initial_total = rows[0]["total"]
    assert initial_total >= 2

    # 2. Second ingest with SAME batch_id must be skipped (idempotency)
    r2 = load_batch(batch_id, transformed, events_in=2, accepted=2, rejected=0, rejection_reasons=reasons)
    assert r2["duplicate_batch"] is True

    # Total must NOT have changed
    rows_after = execute_query("SELECT SUM(cnt) as total FROM demand_cells WHERE res = 9", {})
    assert rows_after[0]["total"] == initial_total

    # 3. Third ingest with NEW batch_id must add to the counts (additive upsert)
    new_batch_id = f"test-batch-new-{datetime.now(timezone.utc).timestamp()}"
    r3 = load_batch(new_batch_id, transformed, events_in=2, accepted=2, rejected=0, rejection_reasons=reasons)
    assert r3["duplicate_batch"] is False

    rows_added = execute_query("SELECT SUM(cnt) as total FROM demand_cells WHERE res = 9", {})
    assert rows_added[0]["total"] == initial_total + 2
