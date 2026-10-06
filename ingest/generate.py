import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Hotspots around Bangalore (default city)
DEFAULT_HOTSPOTS = [
    {"name": "Indiranagar", "lat": 12.9784, "lng": 77.6408, "weight": 0.30, "sigma": 0.012},
    {"name": "Koramangala", "lat": 12.9352, "lng": 77.6245, "weight": 0.25, "sigma": 0.014},
    {"name": "Whitefield",  "lat": 12.9698, "lng": 77.7499, "weight": 0.18, "sigma": 0.016},
    {"name": "MG Road",     "lat": 12.9756, "lng": 77.6066, "weight": 0.17, "sigma": 0.010},
    {"name": "HSR Layout",  "lat": 12.9121, "lng": 77.6446, "weight": 0.10, "sigma": 0.012},
]

CATEGORIES = ["food", "cab", "grocery", "pharmacy"]
CATEGORY_WEIGHTS = [0.45, 0.30, 0.15, 0.10]

def generate_synthetic_events_df(
    n_events: int = 1_000_000,
    days: int = 14,
    start_date: str = "2026-09-01T00:00:00Z",
    seed: int = 42,
    anomaly_spike: bool = True
) -> pd.DataFrame:
    """
    Generates synthetic geo-tagged events according to Section 5.1:
      - Spatial Gaussian mixture around realistic urban hotspots
      - Temporal mixture: lunch peak (~13:00) + dinner peak (~20:00) + weekend boost
      - Weighted category assignment
      - Anomaly injection on a chosen day in Koramangala
      - Guaranteed reproducibility via fixed seed
    """
    rng = np.random.default_rng(seed)

    # 1. Hotspot selection
    weights = np.array([h["weight"] for h in DEFAULT_HOTSPOTS])
    weights /= weights.sum()
    hotspot_indices = rng.choice(len(DEFAULT_HOTSPOTS), size=n_events, p=weights)

    lats = np.empty(n_events, dtype=np.float64)
    lngs = np.empty(n_events, dtype=np.float64)

    for idx, spot in enumerate(DEFAULT_HOTSPOTS):
        mask = (hotspot_indices == idx)
        count = int(mask.sum())
        if count > 0:
            lats[mask] = rng.normal(spot["lat"], spot["sigma"], size=count)
            lngs[mask] = rng.normal(spot["lng"], spot["sigma"], size=count)

    # 2. Categories
    categories = rng.choice(CATEGORIES, size=n_events, p=CATEGORY_WEIGHTS)

    # 3. Temporal generation
    base_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))

    # Day selection (0 to days - 1)
    day_offsets = rng.integers(0, days, size=n_events)

    # Hour generation: bimodal (lunch peak mu=13, sigma=1.5; dinner peak mu=20, sigma=1.8; plus background)
    # Mixture: 40% lunch, 45% dinner, 15% other hours
    hour_choices = rng.choice([0, 1, 2], size=n_events, p=[0.40, 0.45, 0.15])

    hours = np.empty(n_events, dtype=np.float64)

    # Lunch peak
    m0 = (hour_choices == 0)
    hours[m0] = rng.normal(13.0, 1.5, size=int(m0.sum()))

    # Dinner peak
    m1 = (hour_choices == 1)
    hours[m1] = rng.normal(20.0, 1.8, size=int(m1.sum()))

    # Background
    m2 = (hour_choices == 2)
    hours[m2] = rng.uniform(0.0, 24.0, size=int(m2.sum()))

    # Clip hours to [0, 23.99]
    hours = np.clip(hours, 0.0, 23.999)

    # Calculate timestamps in seconds
    seconds_in_day = hours * 3600.0
    total_seconds = day_offsets * 86400.0 + seconds_in_day

    # Inject Anomaly: Add extra 20,000 events to Koramangala on Day 10 (spike in food/cab)
    if anomaly_spike and n_events >= 50_000:
        spike_n = min(25_000, n_events // 20)
        spike_lats = rng.normal(12.9352, 0.008, size=spike_n)
        spike_lngs = rng.normal(77.6245, 0.008, size=spike_n)
        spike_cats = rng.choice(["food", "cab"], size=spike_n, p=[0.7, 0.3])
        spike_days = np.full(spike_n, min(10, days - 1))
        spike_hours = np.clip(rng.normal(20.5, 1.0, size=spike_n), 18.0, 23.5)
        spike_secs = spike_days * 86400.0 + spike_hours * 3600.0

        lats = np.concatenate([lats, spike_lats])
        lngs = np.concatenate([lngs, spike_lngs])
        categories = np.concatenate([categories, spike_cats])
        total_seconds = np.concatenate([total_seconds, spike_secs])

    # Convert to ISO strings
    # Vectorized conversion via pd.to_datetime
    base_ts = pd.Timestamp(base_dt)
    timestamps = base_ts + pd.to_timedelta(total_seconds, unit="s")
    ts_strings = timestamps.strftime("%Y-%m-%dT%H:%M:%SZ")

    df = pd.DataFrame({
        "lat": np.round(lats, 6),
        "lng": np.round(lngs, 6),
        "ts": ts_strings,
        "category": categories
    })

    return df

def generate_and_save_dataset(
    n_events: int = 1_000_000,
    days: int = 14,
    output_dir: str = "data/raw",
    chunk_size: int = 100_000
) -> list[str]:
    """
    Generates and saves the dataset into chunked Parquet files.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"Generating {n_events:,} events across {days} days...")
    df = generate_synthetic_events_df(n_events=n_events, days=days)

    total_rows = len(df)
    files = []
    num_chunks = (total_rows + chunk_size - 1) // chunk_size

    for i in range(num_chunks):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, total_rows)
        chunk_df = df.iloc[start_idx:end_idx]
        file_path = out_path / f"events_part_{i:03d}.parquet"
        chunk_df.to_parquet(file_path, index=False)
        files.append(str(file_path))
        print(f"  Wrote {len(chunk_df):,} events to {file_path}")

    print(f"Successfully generated {total_rows:,} events across {len(files)} files.")
    return files

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demandly Synthetic Event Generator")
    parser.add_argument("--events", type=int, default=1_000_000, help="Number of events (default: 1,000,000)")
    parser.add_argument("--days", type=int, default=14, help="Time window days (default: 14)")
    parser.add_argument("--output", type=str, default="data/raw", help="Output directory")
    parser.add_argument("--chunk-size", type=int, default=100_000, help="Chunk size (default: 100,000)")
    args = parser.parse_args()

    generate_and_save_dataset(
        n_events=args.events,
        days=args.days,
        output_dir=args.output,
        chunk_size=args.chunk_size
    )
