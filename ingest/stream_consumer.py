import argparse
import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from api.cache import cache_manager
from ingest.generate import generate_synthetic_events_df
from ingest.load import load_batch
from ingest.transform import transform_events_to_cells
from ingest.validate import validate_events

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

STREAM_KEY = "demandly:stream:events"
GROUP_NAME = "demandly_group"
CONSUMER_NAME = "worker_1"

def produce_stream(rate_per_sec: int = 200, duration_sec: int = 30):
    """
    Simulates real-time event streaming by pushing events to a Redis Stream.
    """
    client = cache_manager.get_client()
    if not client:
        logger.error("Redis client is not available. Streaming requires Redis.")
        return

    logger.info(f"Producing ~{rate_per_sec} events/sec to stream '{STREAM_KEY}' for {duration_sec}s...")
    start_time = time.time()
    batch_idx = 0

    while time.time() - start_time < duration_sec:
        # Generate small batch
        now_iso = datetime.now(timezone.utc).isoformat()
        df = generate_synthetic_events_df(n_events=rate_per_sec, days=1, start_date=now_iso, anomaly_spike=False)
        for _, row in df.iterrows():
            payload = {
                "lat": float(row["lat"]),
                "lng": float(row["lng"]),
                "ts": row["ts"],
                "category": row["category"]
            }
            client.xadd(STREAM_KEY, {"data": json.dumps(payload)})

        batch_idx += 1
        time.sleep(1.0)

    logger.info("Streaming producer finished.")

def consume_stream(batch_size: int = 5000, poll_timeout_ms: int = 2000):
    """
    Consumes events from Redis Stream in micro-batches and processes them through the standard pipeline.
    """
    client = cache_manager.get_client()
    if not client:
        logger.error("Redis client is not available for stream consumer.")
        return

    try:
        client.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except Exception:
        pass  # Group already exists

    logger.info(f"Stream consumer started on group '{GROUP_NAME}', reading micro-batches (N={batch_size})...")

    batch_counter = 0
    while True:
        try:
            entries = client.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=batch_size,
                block=poll_timeout_ms
            )

            if not entries:
                continue

            events = []
            msg_ids = []

            for stream_name, msg_list in entries:
                for msg_id, data in msg_list:
                    raw_str = data.get("data")
                    if raw_str:
                        events.append(json.loads(raw_str))
                    msg_ids.append(msg_id)

            if not events:
                continue

            batch_counter += 1
            batch_id = f"stream-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{batch_counter:04d}"
            df = pd.DataFrame(events)

            # Stage 1: Validate
            valid_df, rejection_counts = validate_events(df)
            events_in = len(df)
            accepted = len(valid_df)
            rejected = events_in - accepted

            # Stage 2 & 3: Transform & Multi-res
            rollup_df = transform_events_to_cells(valid_df)

            # Stage 4: Load
            _ = load_batch(
                batch_id=batch_id,
                rollup_df=rollup_df,
                events_in=events_in,
                accepted=accepted,
                rejected=rejected,
                rejection_reasons=rejection_counts
            )

            # Acknowledge messages
            client.xack(STREAM_KEY, GROUP_NAME, *msg_ids)
            logger.info(f"Processed stream batch {batch_id}: accepted={accepted}, rejected={rejected}")

        except KeyboardInterrupt:
            logger.info("Stream consumer stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error in stream consumer loop: {e}")
            time.sleep(1.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demandly Stream Simulation")
    parser.add_argument("--produce", action="store_true", help="Run producer simulation")
    parser.add_argument("--consume", action="store_true", help="Run consumer service")
    parser.add_argument("--rate", type=int, default=200, help="Events per second to produce")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds")
    args = parser.parse_args()

    if args.produce:
        produce_stream(rate_per_sec=args.rate, duration_sec=args.duration)
    elif args.consume:
        consume_stream()
    else:
        print("Specify --produce or --consume")
