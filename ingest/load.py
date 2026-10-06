import logging
from datetime import datetime
from typing import Any

import pandas as pd

from api.cache import cache_manager
from api.db import get_pg_pool, get_sqlite_conn

logger = logging.getLogger(__name__)

def _fmt_bucket(val: Any) -> str:
    if isinstance(val, (pd.Timestamp, datetime)):
        return val.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(val).replace("+00:00", "Z")

def load_batch(
    batch_id: str,
    rollup_df: pd.DataFrame,
    events_in: int,
    accepted: int,
    rejected: int,
    rejection_reasons: dict[str, int]
) -> dict[str, Any]:
    """
    Loads transformed batch into demand_cells within an atomic transaction.
    Guarantees:
      1. Idempotency: duplicate batch_id is skipped.
      2. Atomicity: batch info, rejected reasons, and cell increments commit together.
      3. Cache invalidation: increments data_version on success.
    """
    pool = get_pg_pool()

    if pool is not None:
        try:
            with pool.connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        # 1. Idempotency check
                        cur.execute(
                            "SELECT 1 FROM ingest_batches WHERE batch_id = %s",
                            (batch_id,)
                        )
                        if cur.fetchone():
                            logger.info(f"Batch {batch_id} already ingested, skipping.")
                            return {"accepted": accepted, "rejected": rejected, "duplicate_batch": True}

                        # 2. Record batch
                        cur.execute(
                            """
                            INSERT INTO ingest_batches (batch_id, events_in, accepted, rejected)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (batch_id, events_in, accepted, rejected)
                        )

                        # 3. Record rejection summaries
                        for reason, n in rejection_reasons.items():
                            if n > 0:
                                cur.execute(
                                    """
                                    INSERT INTO rejected_summary (batch_id, reason, n)
                                    VALUES (%s, %s, %s)
                                    """,
                                    (batch_id, reason, n)
                                )

                        # 4. Upsert cell counts
                        if not rollup_df.empty:
                            records = []
                            for _, row in rollup_df.iterrows():
                                b_val = row["bucket"]
                                b_str = _fmt_bucket(b_val)
                                records.append((
                                    int(row["res"]),
                                    str(row["h3"]),
                                    b_str,
                                    str(row["category"]),
                                    int(row["cnt"]),
                                    float(row["lat_c"]),
                                    float(row["lng_c"])
                                ))

                            cur.executemany(
                                """
                                INSERT INTO demand_cells (res, h3, bucket, category, cnt, lat_c, lng_c)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (res, h3, bucket, category)
                                DO UPDATE SET cnt = demand_cells.cnt + EXCLUDED.cnt
                                """,
                                records
                            )

            # Invalidate Redis cache
            cache_manager.increment_data_version()
            return {"accepted": accepted, "rejected": rejected, "duplicate_batch": False}

        except Exception as e:
            logger.warning(f"PostgreSQL batch load error: {e}. Falling back to SQLite if applicable.")

    # SQLite fallback
    conn = get_sqlite_conn()
    try:
        cur = conn.cursor()
        # 1. Idempotency check
        cur.execute("SELECT 1 FROM ingest_batches WHERE batch_id = ?", (batch_id,))
        if cur.fetchone():
            return {"accepted": accepted, "rejected": rejected, "duplicate_batch": True}

        # 2. Record batch
        cur.execute(
            """
            INSERT INTO ingest_batches (batch_id, events_in, accepted, rejected)
            VALUES (?, ?, ?, ?)
            """,
            (batch_id, events_in, accepted, rejected)
        )

        # 3. Record rejection summaries
        for reason, n in rejection_reasons.items():
            if n > 0:
                cur.execute(
                    """
                    INSERT INTO rejected_summary (batch_id, reason, n)
                    VALUES (?, ?, ?)
                    """,
                    (batch_id, reason, n)
                )

        # 4. Upsert cell counts
        if not rollup_df.empty:
            records = []
            for _, row in rollup_df.iterrows():
                b_val = row["bucket"]
                b_str = _fmt_bucket(b_val)
                records.append((
                    int(row["res"]),
                    str(row["h3"]),
                    b_str,
                    str(row["category"]),
                    int(row["cnt"]),
                    float(row["lat_c"]),
                    float(row["lng_c"])
                ))

            cur.executemany(
                """
                INSERT INTO demand_cells (res, h3, bucket, category, cnt, lat_c, lng_c)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (res, h3, bucket, category)
                DO UPDATE SET cnt = demand_cells.cnt + excluded.cnt
                """,
                records
            )

        conn.commit()
        # Invalidate cache
        cache_manager.increment_data_version()
        return {"accepted": accepted, "rejected": rejected, "duplicate_batch": False}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error loading batch {batch_id} into SQLite: {e}")
        raise e
    finally:
        conn.close()
