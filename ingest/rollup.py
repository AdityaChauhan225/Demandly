import argparse
import logging
from datetime import datetime, timedelta, timezone

from api.cache import cache_manager
from api.db import get_pg_pool, get_sqlite_conn

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def format_iso(dt: datetime) -> str:
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def execute_rollup_range(day_start: datetime, day_end: datetime) -> int:
    """
    Computes daily rollups from demand_cells into demand_daily for the given window.
    Crucial property: OVERWRITES (set-based idempotency), does NOT add!
    """
    day_start_iso = format_iso(day_start)
    day_end_iso = format_iso(day_end)

    pool = get_pg_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO demand_daily (res, h3, bucket, category, cnt, lat_c, lng_c)
                            SELECT res, h3, date_trunc('day', bucket), category, SUM(cnt), MIN(lat_c), MIN(lng_c)
                            FROM demand_cells
                            WHERE bucket >= %s AND bucket < %s
                            GROUP BY res, h3, date_trunc('day', bucket), category
                            ON CONFLICT (res, h3, bucket, category)
                            DO UPDATE SET cnt = EXCLUDED.cnt
                            """,
                            (day_start_iso, day_end_iso)
                        )
                        affected = cur.rowcount
            cache_manager.increment_data_version()
            logger.info(f"Rolled up {affected} daily rows in PostgreSQL between {day_start_iso} and {day_end_iso}")
            return affected
        except Exception as e:
            logger.warning(f"PostgreSQL rollup failed: {e}. Falling back to SQLite.")

    # SQLite rollup
    conn = get_sqlite_conn()
    try:
        cur = conn.cursor()
        # In SQLite, bucket is stored as ISO string e.g. 2026-09-01T12:00:00Z
        # date_trunc('day') is substr(bucket, 1, 10) || 'T00:00:00Z'
        query = """
        INSERT INTO demand_daily (res, h3, bucket, category, cnt, lat_c, lng_c)
        SELECT
            res,
            h3,
            substr(bucket, 1, 10) || 'T00:00:00Z' AS day_bucket,
            category,
            SUM(cnt) AS cnt,
            MIN(lat_c) AS lat_c,
            MIN(lng_c) AS lng_c
        FROM demand_cells
        WHERE bucket >= ? AND bucket < ?
        GROUP BY res, h3, substr(bucket, 1, 10) || 'T00:00:00Z', category
        ON CONFLICT (res, h3, bucket, category)
        DO UPDATE SET cnt = excluded.cnt
        """
        cur.execute(query, (day_start_iso, day_end_iso))
        affected = cur.rowcount
        conn.commit()
        cache_manager.increment_data_version()
        logger.info(f"Rolled up {affected} daily rows in SQLite between {day_start_iso} and {day_end_iso}")
        return affected
    finally:
        conn.close()

def rollup_recent():
    """
    Scheduled hourly job: Recomputes yesterday and today's daily rollups.
    """
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    yesterday_start = today_start - timedelta(days=1)
    tomorrow_start = today_start + timedelta(days=1)

    logger.info("Executing scheduled daily rollup for yesterday and today...")
    execute_rollup_range(yesterday_start, tomorrow_start)

def rollup_all():
    """
    Backfills all available dates in demand_cells into demand_daily.
    """
    logger.info("Backfilling all historical rollups from demand_cells...")
    execute_rollup_range(datetime(2020, 1, 1, tzinfo=timezone.utc), datetime(2030, 1, 1, tzinfo=timezone.utc))

def start_scheduler():
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler()
    # Run rollup every hour
    scheduler.add_job(rollup_recent, "cron", minute=5)
    logger.info("Starting rollup scheduler (runs at minute 5 of every hour)...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Rollup scheduler stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demandly Rollup Worker")
    parser.add_argument("--schedule", action="store_true", help="Run background scheduler")
    parser.add_argument("--backfill", action="store_true", help="Backfill all available dates")
    parser.add_argument("--start", type=str, help="Start date (ISO)")
    parser.add_argument("--end", type=str, help="End date (ISO)")
    args = parser.parse_args()

    if args.schedule:
        start_scheduler()
    elif args.backfill:
        rollup_all()
    elif args.start and args.end:
        s = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        execute_rollup_range(s, e)
    else:
        rollup_recent()
