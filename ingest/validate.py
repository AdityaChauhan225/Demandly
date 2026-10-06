from datetime import datetime, timezone

import pandas as pd

ALLOWED_CATEGORIES = {"food", "cab", "grocery", "pharmacy"}
MIN_TIMESTAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)

def validate_events(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Validates a batch of raw events according to Section 5.2.
    Rejects invalid rows and counts reasons.
    Rejected events are NOT stored.
    """
    rejection_counts = {
        "bad_coord": 0,
        "null_island": 0,
        "missing_coord": 0,
        "bad_ts": 0,
        "ts_out_of_range": 0,
        "bad_category": 0,
    }

    if df.empty:
        return df, rejection_counts

    now_utc = datetime.now(timezone.utc)
    # Allow small clock skew (e.g., up to 1 day ahead)
    max_timestamp = now_utc + pd.Timedelta(days=1)

    # 1. Missing coordinates
    missing_coord_mask = df["lat"].isna() | df["lng"].isna()
    rejection_counts["missing_coord"] = int(missing_coord_mask.sum())
    valid_mask = ~missing_coord_mask

    # 2. Null Island (0.0, 0.0)
    null_island_mask = valid_mask & (df["lat"] == 0.0) & (df["lng"] == 0.0)
    rejection_counts["null_island"] = int(null_island_mask.sum())
    valid_mask &= ~null_island_mask

    # 3. Bad coords (out of bounds)
    bad_coord_mask = valid_mask & ((df["lat"] < -90.0) | (df["lat"] > 90.0) | (df["lng"] < -180.0) | (df["lng"] > 180.0))
    rejection_counts["bad_coord"] = int(bad_coord_mask.sum())
    valid_mask &= ~bad_coord_mask

    # 4. Bad timestamp parsing
    ts_parsed = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    bad_ts_mask = valid_mask & ts_parsed.isna()
    rejection_counts["bad_ts"] = int(bad_ts_mask.sum())
    valid_mask &= ~bad_ts_mask

    # 5. Timestamp out of range
    ts_range_mask = valid_mask & ((ts_parsed < MIN_TIMESTAMP) | (ts_parsed > max_timestamp))
    rejection_counts["ts_out_of_range"] = int(ts_range_mask.sum())
    valid_mask &= ~ts_range_mask

    # 6. Bad category
    bad_cat_mask = valid_mask & (~df["category"].isin(ALLOWED_CATEGORIES))
    rejection_counts["bad_category"] = int(bad_cat_mask.sum())
    valid_mask &= ~bad_cat_mask

    valid_df = df[valid_mask].copy()
    valid_df["ts"] = ts_parsed[valid_mask]

    return valid_df, rejection_counts
