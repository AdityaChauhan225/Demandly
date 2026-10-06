import argparse
import time
from datetime import datetime, timezone

from api.db import init_db
from ingest.generate import generate_synthetic_events_df
from ingest.load import load_batch
from ingest.rollup import rollup_all
from ingest.transform import transform_events_to_cells
from ingest.validate import validate_events


def run_seed(total_events: int = 1_000_000, batch_size: int = 100_000, days: int = 14):
    print("=" * 60)
    print(f"Demandly Pipeline Seeding: {total_events:,} events ({days} days)")
    print("=" * 60)

    # 1. Initialize schema
    print("\n[1/4] Ensuring database schema is initialized...")
    init_db()

    # 2. Generate events
    start_gen = time.time()
    print(f"\n[2/4] Generating {total_events:,} synthetic events...")
    raw_df = generate_synthetic_events_df(n_events=total_events, days=days)
    gen_time = time.time() - start_gen
    print(f"Generated {len(raw_df):,} events in {gen_time:.2f}s ({len(raw_df)/gen_time:,.0f} events/sec)")

    # 3. Ingest in batches
    print(f"\n[3/4] Ingesting through privacy pipeline (batch size: {batch_size:,})...")
    total_accepted = 0
    total_rejected = 0
    num_batches = (len(raw_df) + batch_size - 1) // batch_size

    start_ingest = time.time()
    for b_idx in range(num_batches):
        b_start = b_idx * batch_size
        b_end = min(b_start + batch_size, len(raw_df))
        batch_slice = raw_df.iloc[b_start:b_end].copy()

        batch_id = f"seed-batch-{b_idx+1:03d}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        # Validate
        valid_df, rejection_counts = validate_events(batch_slice)
        b_events_in = len(batch_slice)
        b_accepted = len(valid_df)
        b_rejected = b_events_in - b_accepted

        # Transform (Privacy Boundary: lat/lng dropped, H3 bucketing & parents)
        rollup_df = transform_events_to_cells(valid_df)

        # Load
        _ = load_batch(
            batch_id=batch_id,
            rollup_df=rollup_df,
            events_in=b_events_in,
            accepted=b_accepted,
            rejected=b_rejected,
            rejection_reasons=rejection_counts
        )

        total_accepted += b_accepted
        total_rejected += b_rejected
        pct = ((b_idx + 1) / num_batches) * 100
        print(f"  Batch {b_idx+1:02d}/{num_batches:02d} ({pct:5.1f}%): "
              f"accepted={b_accepted:,} rejected={b_rejected:,} cell_rows={len(rollup_df):,}")

    ingest_time = time.time() - start_ingest
    overall_throughput = total_accepted / max(0.001, ingest_time)
    print("\nIngestion Complete:")
    print(f"  Total accepted: {total_accepted:,}")
    print(f"  Total rejected: {total_rejected:,}")
    print(f"  Ingest duration: {ingest_time:.2f}s")
    print(f"  Throughput: {overall_throughput:,.0f} events/sec")

    # 4. Precompute daily rollups
    print("\n[4/4] Precomputing daily rollups into demand_daily...")
    start_rollup = time.time()
    rollup_all()
    rollup_time = time.time() - start_rollup
    print(f"Daily rollups generated in {rollup_time:.2f}s")

    print("\n" + "=" * 60)
    print("Seed Complete! Privacy boundary enforced: raw lat/lng discarded.")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Demandly Pipeline")
    parser.add_argument("--events", type=int, default=1_000_000, help="Number of events (default: 1,000,000)")
    parser.add_argument("--batch-size", type=int, default=100_000, help="Batch size (default: 100,000)")
    parser.add_argument("--days", type=int, default=14, help="Days range (default: 14)")
    args = parser.parse_args()

    run_seed(total_events=args.events, batch_size=args.batch_size, days=args.days)
