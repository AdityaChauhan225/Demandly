from datetime import datetime, timezone

import pandas as pd

from api.db import execute_query, init_db
from ingest.load import load_batch
from ingest.rollup import execute_rollup_range
from ingest.transform import transform_events_to_cells
from ingest.validate import validate_events


def test_daily_rollup_matches_hourly_and_is_idempotent():
    init_db()

    # Create events spanning 3 hours on 2026-09-05
    events = [
        {"lat": 12.971, "lng": 77.591, "ts": "2026-09-05T08:15:00Z", "category": "food"},
        {"lat": 12.971, "lng": 77.591, "ts": "2026-09-05T08:45:00Z", "category": "food"},
        {"lat": 12.971, "lng": 77.591, "ts": "2026-09-05T13:20:00Z", "category": "food"},
        {"lat": 12.971, "lng": 77.591, "ts": "2026-09-05T20:10:00Z", "category": "food"},
    ]
    df = pd.DataFrame(events)
    valid_df, reasons = validate_events(df)
    rollup_df = transform_events_to_cells(valid_df)

    batch_id = f"test-rollup-batch-{datetime.now(timezone.utc).timestamp()}"
    load_batch(batch_id, rollup_df, events_in=4, accepted=4, rejected=0, rejection_reasons=reasons)

    # Verify hourly counts
    hourly_rows = execute_query(
        """
        SELECT SUM(cnt) as hourly_sum
        FROM demand_cells
        WHERE res = 9 AND bucket >= '2026-09-05T00:00:00Z' AND bucket < '2026-09-06T00:00:00Z'
        """,
        {}
    )
    hourly_sum = hourly_rows[0]["hourly_sum"]
    assert hourly_sum >= 4

    # Run daily rollup for 2026-09-05
    start_dt = datetime(2026, 9, 5, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 9, 6, 0, 0, 0, tzinfo=timezone.utc)
    execute_rollup_range(start_dt, end_dt)

    daily_rows = execute_query(
        """
        SELECT SUM(cnt) as daily_sum
        FROM demand_daily
        WHERE res = 9 AND bucket >= '2026-09-05T00:00:00Z' AND bucket < '2026-09-06T00:00:00Z'
        """,
        {}
    )
    daily_sum = daily_rows[0]["daily_sum"]

    # Daily sum must exactly equal hourly sum
    assert daily_sum == hourly_sum, "Daily rollup sum must equal the sum of hourly aggregates"

    # Re-running rollup MUST NOT double count (idempotent overwrite)
    execute_rollup_range(start_dt, end_dt)

    daily_rows_rerun = execute_query(
        """
        SELECT SUM(cnt) as daily_sum
        FROM demand_daily
        WHERE res = 9 AND bucket >= '2026-09-05T00:00:00Z' AND bucket < '2026-09-06T00:00:00Z'
        """,
        {}
    )
    assert daily_rows_rerun[0]["daily_sum"] == daily_sum, "Re-running rollup must overwrite, never double-count"
