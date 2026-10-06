# Demandly — Implementation Plan

> A privacy-preserving, high-performance geospatial demand analytics platform.
> Ingests geo-tagged events, buckets them into H3 hexagons, discards exact coordinates,
> and serves fast heatmap and ranking queries to an interactive dashboard.

Spec reference: **DEA-G08 · Data Engineering & Analytics · Demandly**

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Requirements](#2-requirements)
3. [Tech stack](#3-tech-stack)
4. [System architecture](#4-system-architecture)
5. [Data pipeline in detail](#5-data-pipeline-in-detail)
6. [Data model](#6-data-model)
7. [Privacy design](#7-privacy-design)
8. [API specification](#8-api-specification)
9. [Caching design](#9-caching-design)
10. [Background rollups](#10-background-rollups)
11. [Frontend design](#11-frontend-design)
12. [Benchmark plan](#12-benchmark-plan)
13. [Testing strategy](#13-testing-strategy)
14. [Security and operations](#14-security-and-operations)
15. [Deployment](#15-deployment)
16. [Repository layout](#16-repository-layout)
17. [Milestones and acceptance criteria](#17-milestones-and-acceptance-criteria)
18. [Risks and limitations](#18-risks-and-limitations)
19. [Definition of done](#19-definition-of-done)

---

## 1. Project overview

### 1.1 Problem

Organisations that handle location-tagged events (orders, ride requests, service calls) need to know
**where** and **when** demand is high. Two things make this hard:

- **Scale:** scanning millions of raw rows on every map interaction is too slow.
- **Privacy:** exact coordinates are sensitive, and storing or exposing them creates legal and ethical risk.

### 1.2 Solution

Demandly converts each event into an **H3 hexagon cell + hourly time bucket**, discards the raw
coordinates, stores only aggregated counts, and serves them through a cached API to a map dashboard.

### 1.3 Goals

| # | Goal |
|---|---|
| G1 | Show demand per area and time window as a heatmap |
| G2 | Rank high-demand zones and detect rising demand |
| G3 | Never store or expose exact event coordinates |
| G4 | Stay fast with 1M+ events, with measured proof |
| G5 | Be reproducible (Docker) and demoable (live link) |

### 1.4 Non-goals

- Real user accounts, payments, or a production auth system
- Real-world data sources (synthetic data only, with the ingestion path designed to accept real ones)
- Formal differential privacy guarantees (the design is privacy-aware, not formally private)
- Routing, dispatch, or pricing logic

---

## 2. Requirements

### 2.1 Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR1 | Generate a reproducible synthetic dataset of 1M+ geo-tagged events with hotspots, time-of-day patterns and categories | Must |
| FR2 | Ingest events in batches: validate, convert to H3, drop coordinates, aggregate, store | Must |
| FR3 | Store counts at multiple H3 resolutions (6, 7, 8, 9) and hourly granularity | Must |
| FR4 | Serve cell counts for a map bounding box, zoom level, time range and category filter | Must |
| FR5 | Return a ranked list of top zones for a window, with growth vs. the previous equal window | Must |
| FR6 | Return the hour-of-day profile (peak windows) for a selected zone | Must |
| FR7 | Suppress cells below a minimum count K in every response | Must |
| FR8 | Pick the H3 resolution automatically from the map zoom | Must |
| FR9 | Cache query results and invalidate them when data changes | Must |
| FR10 | Precompute daily rollups on a schedule and use them for long windows | Must |
| FR11 | Interactive dashboard: map, time range control, category filter, top-zones sidebar, zone detail chart | Must |
| FR12 | Privacy-mode demo toggle (raw points vs. anonymised hexes) on the demo dataset | Should |
| FR13 | Deterministic noise on counts | Should |
| FR14 | Streaming simulation via Redis Streams with a live-updating dashboard | Could |
| FR15 | Simple per-zone demand forecast | Could |

### 2.2 Non-functional requirements

| ID | Requirement | Target (to be validated by benchmarks) |
|---|---|---|
| NFR1 | Warm-cache `/cells` latency | p95 well under 100 ms at 50 concurrent users |
| NFR2 | Cold-cache `/cells` latency | p95 under 500 ms |
| NFR3 | Ingest throughput | Report events/sec measured on the dev machine |
| NFR4 | Response size | Max 5,000 cells per response |
| NFR5 | Reproducibility | Fresh clone running in 3 commands |
| NFR6 | Privacy | No persisted table contains an event's exact location |
| NFR7 | Test coverage | Core logic (ingest, privacy, cache, rollups) covered by automated tests |

The targets are goals. Report only what is measured.

### 2.3 Constraints

- Solo developer, part-time, roughly 2–3 weeks
- Free-tier hosting for the live demo (verify current limits)
- Must run locally with Docker only

---

## 3. Tech stack

| Layer | Technology | Role |
|---|---|---|
| Language | Python 3.11+ | Backend, ingestion, benchmarks |
| Spatial index | `h3` (h3-py **v4**) | Hex bucketing, parent/child hierarchy |
| Data processing | Pandas, NumPy | Data generation, batch aggregation |
| API | FastAPI, Uvicorn, Pydantic | HTTP API, validation, auto docs |
| Database | PostgreSQL 16 | Rollup storage, indexes, upserts |
| DB driver | psycopg 3, psycopg_pool | Pooling, `COPY` |
| Cache | Redis 7, redis-py | Query cache, version counter, optional streams |
| Scheduler | APScheduler | Rollup jobs |
| Frontend | React, Vite, TypeScript | UI |
| Map | MapLibre GL JS, react-map-gl | Basemap |
| Visualisation | deck.gl (`H3HexagonLayer`) | Hex layer |
| Charts | Recharts | Hour-of-day and trend charts |
| Containers | Docker, Docker Compose | Local and deployment packaging |
| Tests | pytest, pytest-asyncio, httpx | Unit and integration tests |
| Lint/format | Ruff | Code quality |
| CI | GitHub Actions | Run tests on push |
| Load testing | Locust (or httpx + asyncio) | Benchmarks |

**h3-py v4 note:** use `latlng_to_cell`, `cell_to_latlng`, `cell_to_parent`, `cell_to_boundary`.
The v3 names (`geo_to_h3`, `h3_to_parent`) will fail.

---

## 4. System architecture

### 4.1 Component diagram

```
 ┌────────────────────┐
 │ Event sources      │  synthetic generator (demo)
 │ (apps / devices /  │  Kafka consumer, batch job, API push (production)
 │  batch exports)    │
 └─────────┬──────────┘
           │  batches of raw events (lat, lng, ts, category)
           ▼
 ┌────────────────────────────────────────────────────────────┐
 │ INGESTION SERVICE  (privacy boundary)                       │
 │  validate → floor time → H3(res 9) → DROP lat/lng →         │
 │  aggregate → derive parents (8,7,6) → bulk upsert           │
 └─────────┬──────────────────────────────────────────────────┘
           │  only (res, h3, hour, category, count)
           ▼
 ┌────────────────────────────┐        ┌──────────────────────┐
 │ POSTGRESQL                 │◄───────│ ROLLUP JOB           │
 │  demand_cells  (hourly)    │        │ hourly → daily        │
 │  demand_daily  (daily)     │───────►│ bumps data_version    │
 │  ingest_batches            │        └──────────────────────┘
 │  rejected_summary          │
 └─────────┬──────────────────┘
           │ SQL aggregation
           ▼
 ┌────────────────────────────┐        ┌──────────────────────┐
 │ FASTAPI                    │◄──────►│ REDIS                │
 │  zoom→res, window→table    │ cache  │  query cache          │
 │  K-suppression, noise      │        │  data_version         │
 └─────────┬──────────────────┘        └──────────────────────┘
           │ JSON (h3 id + count only)
           ▼
 ┌────────────────────────────┐
 │ REACT + deck.gl + MapLibre │
 │  heatmap, filters, ranking │
 └────────────────────────────┘
```

### 4.2 Architectural principles

1. **Privacy boundary at ingestion.** Raw coordinates exist only in the input batch and in process
   memory. Everything past the ingestion service is aggregated.
2. **Pre-aggregate, don't scan.** Queries read small rollup tables, never raw events.
3. **Bounded responses.** Zoom→resolution mapping caps the number of cells per response.
4. **Cache with versioned keys.** Data changes invalidate caches by bumping a counter, not by deleting keys.
5. **Idempotent, incremental writes.** Upserts add counts, and batch IDs prevent double application.
6. **Source-agnostic ingestion.** Ingestion takes a batch of events, whatever produced it.

### 4.3 Runtime topology (Docker Compose)

| Service | Image / build | Port | Depends on |
|---|---|---|---|
| `postgres` | postgres:16 | 5432 | n/a |
| `redis` | redis:7 | 6379 | n/a |
| `api` | ./api (FastAPI + Uvicorn) | 8000 | postgres, redis |
| `worker` | ./api (APScheduler entrypoint) | n/a | postgres, redis |
| `web` | ./web (Vite build served as static, or by `api`) | 5173 / 8000 | api |

The `worker` runs the rollup scheduler. The optional stream consumer is added as a further service.

---

## 5. Data pipeline in detail

### 5.1 Stage 0: Event generation (demo source)

**Input:** parameters (event count, days, seed, city center).
**Output:** Parquet files in `data/raw/`, 100k rows each, columns `lat, lng, ts, category`.

Generation logic:

- **Spatial:** choose a hotspot per event by weight, then sample a Gaussian around its center.
- **Temporal:** mixture of a lunch peak (~13:00) and an evening peak (~20:00), uniform across days,
  with a weekend multiplier.
- **Category:** weighted choice from `food, cab, grocery, pharmacy`.
- **Anomaly:** one zone gets a spike on one chosen day, so growth ranking has a real signal.
- **Reproducibility:** fixed seed (`numpy.random.default_rng(42)`).

### 5.2 Stage 1: Validation

Per event, reject if:

| Check | Reason code |
|---|---|
| lat outside [-90, 90] or lng outside [-180, 180] | `bad_coord` |
| lat and lng both exactly 0 | `null_island` |
| coordinate missing / NaN | `missing_coord` |
| timestamp missing or unparseable | `bad_ts` |
| timestamp in the future or before the allowed window | `ts_out_of_range` |
| category not in the allowed set | `bad_category` |

Rejected events are **not stored**. Only a count per reason is recorded in `rejected_summary`
(this preserves the privacy rule, since a rejected event must not leave its coordinates behind).

### 5.3 Stage 2: Transformation (privacy boundary)

```
bucket = floor(ts to hour, UTC)
cell9  = h3.latlng_to_cell(lat, lng, 9)
drop lat, lng                           ← raw coordinates removed from the dataframe
group by (cell9, bucket, category)  →  cnt
```

### 5.4 Stage 3: Multi-resolution expansion

For each target resolution in `(6, 7, 8, 9)`:

1. Take the **unique** `cell9` values in the batch.
2. Map each to its parent: `h3.cell_to_parent(cell9, res)` (identity for res 9).
3. Re-aggregate: `group by (parent, bucket, category) → sum(cnt)`.
4. Attach the cell center: `h3.cell_to_latlng(parent)` → `lat_c, lng_c`.

Computing parents on unique cells (thousands) instead of events (millions) is the key optimisation.

### 5.5 Stage 4: Load

1. Insert a row into `ingest_batches` with the `batch_id`. If it already exists, skip the batch (idempotency).
2. `COPY` the rollup dataframe into a temp staging table.
3. `INSERT ... SELECT ... ON CONFLICT (res, h3, bucket, category) DO UPDATE SET cnt = demand_cells.cnt + EXCLUDED.cnt`.
4. Commit the transaction.
5. `INCR data_version` in Redis (invalidates cached queries).

Steps 1 to 4 run in **one transaction**, so a failure leaves no half-applied batch.

### 5.6 Stage 5: Rollup

A scheduled job recomputes affected days into `demand_daily` from `demand_cells` (set-based and
idempotent: it overwrites the day, never adds), then bumps `data_version`. See [section 10](#10-background-rollups).

### 5.7 Stage 6: Serving

1. Request arrives with bbox, zoom, time range, category.
2. API normalises parameters, builds the cache key, and checks Redis.
3. On a miss: choose resolution and source table, run the SQL aggregation, apply K-suppression
   and noise, store the result in Redis, and return it.
4. The frontend renders hex cells from the IDs.

### 5.8 Stage 7: Streaming mode (optional)

```
producer script → Redis Stream "events" → consumer group → micro-batch (N=5000 or T=2s) → Stage 1–5
```

The consumer reuses the same ingestion function. The dashboard polls or subscribes and sees counts rise
in near real time.

### 5.9 Real-world mapping

| Demo | Production equivalent |
|---|---|
| Generator → Parquet | App/device events → Kafka / Kinesis / Pub-Sub |
| `make seed` batch run | Scheduled batch pull (Airflow/cron) or CDC (Debezium) |
| `POST /events/batch` | Partner or service push |
| Redis Streams consumer | Kafka consumer group |

The ingestion function is identical in every case.

### 5.10 Failure handling

| Failure | Handling |
|---|---|
| Duplicate batch | `batch_id` check, batch skipped |
| Crash mid-batch | Transaction rolls back, batch can be retried safely |
| Late events | Upsert adds to the old hourly bucket, the next rollup corrects the daily row |
| Invalid events | Counted by reason, discarded |
| Redis down | API falls back to direct DB queries (slower, still correct) |
| Postgres down | `/health` reports failure, API returns 503 |

---

## 6. Data model

### 6.1 Tables

```sql
-- Hourly, multi-resolution aggregates (the main serving table)
CREATE TABLE demand_cells (
  res      SMALLINT         NOT NULL CHECK (res IN (6,7,8,9)),
  h3       TEXT             NOT NULL,
  bucket   TIMESTAMPTZ      NOT NULL,           -- start of the hour, UTC
  category TEXT             NOT NULL,
  cnt      INTEGER          NOT NULL CHECK (cnt >= 0),
  lat_c    DOUBLE PRECISION NOT NULL,           -- cell CENTER (not an event location)
  lng_c    DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (res, h3, bucket, category)
);
CREATE INDEX demand_cells_res_bucket ON demand_cells (res, bucket);
CREATE INDEX demand_cells_res_geo    ON demand_cells (res, lat_c, lng_c);

-- Daily rollup, same shape, bucket = start of day
CREATE TABLE demand_daily (LIKE demand_cells INCLUDING ALL);

-- Idempotency + audit
CREATE TABLE ingest_batches (
  batch_id    TEXT PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  events_in   INTEGER NOT NULL,
  accepted    INTEGER NOT NULL,
  rejected    INTEGER NOT NULL
);

-- Rejected events summarised by reason (no coordinates)
CREATE TABLE rejected_summary (
  batch_id TEXT NOT NULL REFERENCES ingest_batches(batch_id),
  reason   TEXT NOT NULL,
  n        INTEGER NOT NULL,
  PRIMARY KEY (batch_id, reason)
);
```

### 6.2 Design rationale

| Decision | Reason |
|---|---|
| One table for all resolutions with a `res` column | Simple queries, one set of indexes |
| `lat_c/lng_c` stored per row | bbox filtering with plain numeric ranges, no PostGIS needed |
| Composite primary key | Prevents duplicates and supports upserts and lookups |
| Separate `demand_daily` | Long windows read about 1/24 of the rows |
| Counts stored as true values; privacy applied at query time | K depends on the queried window, so it can't be applied at write time |

### 6.3 Capacity estimate

Row count is bounded by distinct `(res, cell, hour, category)` combinations, not by event count.
Measure the real size with `SELECT pg_total_relation_size('demand_cells')` after seeding, and report
the raw-vs-rollup size ratio in the benchmark results.

### 6.4 Redis keys

| Key | Value | TTL |
|---|---|---|
| `data_version` | integer, incremented after every ingest or rollup | none |
| `cells:v{N}:{sha1(params)}` | JSON response | 60–300 s |
| `top:v{N}:{sha1(params)}` | JSON response | 60–300 s |
| `zone:v{N}:{sha1(params)}` | JSON response | 60–300 s |

---

## 7. Privacy design

### 7.1 Threat model

| Item | Description |
|---|---|
| Asset | Exact location of individual events |
| Adversary | Someone with access to the dashboard, API, or database (but not the original source system) |
| Goal | Learn where one specific event occurred |
| Out of scope | The adversary who already holds the raw source data |

### 7.2 Layers of protection

| Layer | Mechanism | Protects against |
|---|---|---|
| L1 | Raw lat/lng never persisted | Database leak, insider query |
| L2 | Spatial generalisation to H3 cells | Exact-point inference |
| L3 | K-anonymity suppression (`K`, default 5) | Singling out in sparse cells |
| L4 | Deterministic noise on counts | Exact-count inference |
| L5 | Coarse resolution when zoomed out; finest only when zoomed in | Over-precision at wide scale |

### 7.3 Query-time privacy procedure

```
1. Aggregate counts for the requested window → true_count per cell
2. noisy = max(0, round(true_count + Laplace(0, 1/ε)))     # seeded deterministically
3. Drop cells where noisy < K
4. Return noisy counts
```

- **Threshold on the noisy value**, so suppression itself doesn't reveal the true count.
- **Deterministic seed** = hash(secret_salt, h3, window_start, window_end, category).
  Repeating the same query returns the same noise, so averaging can't cancel it.
- `ε` and `K` are configuration values (`PRIVACY_K`, `PRIVACY_EPSILON`), and noise can be switched off for benchmarks.

### 7.4 Known limitations (to state in the README)

- Not formal differential privacy (no tracked privacy budget).
- **Differencing attacks:** comparing overlapping windows or filters can narrow down small counts.
- **Narrow filters** (tiny time window plus a rare category) can approach individual events, so suppression is applied *after* filtering.
- Cell resolution 9 (~175 m) may still be fine-grained in sparse areas, and the threshold mitigates this.
- Synthetic data has no real individuals, so the design demonstrates the technique rather than a legal guarantee.

### 7.5 Verification

Automated tests (see [section 13](#13-testing-strategy)) assert that no table stores event locations and that
suppressed cells never appear in responses.

---

## 8. API specification

Base path: `/api/v1`. JSON responses. Timestamps are ISO-8601 UTC.

### 8.1 `GET /cells`

Heatmap data for the current map view.

| Param | Type | Required | Notes |
|---|---|---|---|
| `bbox` | `w,s,e,n` floats | yes | Must satisfy w<e, s<n (antimeridian not supported) |
| `zoom` | float | yes | Mapped to H3 resolution |
| `from`, `to` | ISO datetime | yes | `to` exclusive, max range configurable |
| `category` | string | no | Omit for all categories |

```json
{
  "res": 8,
  "source": "hourly",
  "from": "2026-08-10T00:00:00Z",
  "to": "2026-08-11T00:00:00Z",
  "cells": [ { "h3": "88283082a1fffff", "count": 214 } ],
  "suppressed": true,
  "k": 5
}
```

Response headers: `X-Cache: HIT|MISS`, `X-Query-Time-Ms`.
Limit: at most 5,000 cells, and the API returns 422 if the bbox is far larger than the zoom justifies.

### 8.2 `GET /top-zones`

| Param | Type | Notes |
|---|---|---|
| `from`, `to` | ISO datetime | Current window |
| `category` | string | Optional |
| `res` | int | Default 8 |
| `limit` | int | Default 10, max 50 |

```json
{
  "window": { "from": "...", "to": "..." },
  "previous_window": { "from": "...", "to": "..." },
  "zones": [
    { "rank": 1, "h3": "88283082a1fffff", "center": [12.97, 77.59],
      "count": 1840, "previous": 1320, "growth_pct": 39.4 }
  ]
}
```

`center` is the **cell center**. Zones are ranked by `count`, and `growth_pct` is shown beside it.
Zones below K are excluded.

### 8.3 `GET /zones/{h3}/hourly`

Hour-of-day profile for one zone over a date range.

```json
{ "h3": "88283082a1fffff",
  "hours": [ { "hour": 0, "count": 12 }, ..., { "hour": 23, "count": 40 } ],
  "peak_hours": [13, 20] }
```

### 8.4 `GET /meta`

Returns available categories, the data time range, K, and the resolution table, used by the UI to initialise controls.

### 8.5 `POST /events/batch`

Ingestion entrypoint (API-key protected).

```json
{ "batch_id": "2026-10-03T10:00Z-001",
  "events": [ { "lat": 12.97, "lng": 77.59, "ts": "2026-10-03T09:58:12Z", "category": "food" } ] }
```

Response: `{ "accepted": 4980, "rejected": 20, "duplicate_batch": false }`.
Max batch size is configurable (default 10,000 events).

### 8.6 `GET /health`

Checks Postgres and Redis connectivity. Returns 200 or 503.

### 8.7 Zoom → resolution → source

| Zoom | H3 res | Approx. edge |
|---|---|---|
| ≤ 9 | 6 | 3.2 km |
| 10–11 | 7 | 1.2 km |
| 12–13 | 8 | 460 m |
| ≥ 14 | 9 | 175 m |

| Window length | Source table |
|---|---|
| ≤ 7 days | `demand_cells` (hourly) |
| > 7 days | `demand_daily` |

### 8.8 Core queries

```sql
-- /cells
SELECT h3, SUM(cnt) AS count
FROM demand_cells
WHERE res = %(res)s
  AND bucket >= %(from)s AND bucket < %(to)s
  AND lat_c BETWEEN %(s)s AND %(n)s
  AND lng_c BETWEEN %(w)s AND %(e)s
  AND (%(cat)s::text IS NULL OR category = %(cat)s)
GROUP BY h3;
-- noise + K-suppression applied in Python after aggregation
```

```sql
-- /top-zones (current vs. previous window in one pass)
SELECT h3, lat_c, lng_c,
  COALESCE(SUM(cnt) FILTER (WHERE bucket >= %(from)s), 0) AS cur,
  COALESCE(SUM(cnt) FILTER (WHERE bucket <  %(from)s), 0) AS prev
FROM demand_cells
WHERE res = %(res)s
  AND bucket >= %(prev_from)s AND bucket < %(to)s
  AND (%(cat)s::text IS NULL OR category = %(cat)s)
GROUP BY h3, lat_c, lng_c
ORDER BY cur DESC
LIMIT %(overfetch)s;     -- overfetch, then noise + suppress + trim to limit
```

---

## 9. Caching design

### 9.1 Request flow

```
request → normalise params → key = name:v{data_version}:{sha1(params)}
        → Redis GET
            hit  → return (X-Cache: HIT)
            miss → query Postgres → privacy step → Redis SETEX → return (X-Cache: MISS)
```

### 9.2 Normalisation (raises hit rate)

- bbox snapped to 2 decimals (or to the H3 grid at the chosen resolution)
- `from`/`to` floored to the hour
- zoom replaced by the resolution it maps to
- category lowercased, absent value encoded as `*`

### 9.3 Invalidation

After each ingest or rollup, `INCR data_version`. New requests use the new version and old
entries expire by TTL, with no scanning or deleting.

### 9.4 Safety

- Redis failure is caught, and the API serves from Postgres.
- Cache stampede is mitigated with a short per-key lock (`SET NX`) for expensive queries (optional).
- Cached values contain only privacy-processed results, so the cache never holds anything the API wouldn't return.

---

## 10. Background rollups

| Job | Schedule | Action |
|---|---|---|
| `rollup_daily` | hourly | Recompute daily rows for today and yesterday from `demand_cells` |
| `rollup_backfill` | on demand (CLI) | Recompute a given date range |
| `bump_version` | after each job | `INCR data_version` |

```sql
INSERT INTO demand_daily (res, h3, bucket, category, cnt, lat_c, lng_c)
SELECT res, h3, date_trunc('day', bucket), category, SUM(cnt), MIN(lat_c), MIN(lng_c)
FROM demand_cells
WHERE bucket >= %(day_start)s AND bucket < %(day_end)s
GROUP BY res, h3, date_trunc('day', bucket), category
ON CONFLICT (res, h3, bucket, category) DO UPDATE SET cnt = EXCLUDED.cnt;  -- overwrite, not add
```

Rollups **overwrite** (set-based), while ingestion **adds** (incremental). Mixing these up
double-counts data, so test it explicitly.

Optional: retention policy deleting hourly rows older than N days while keeping daily rows.

---

## 11. Frontend design

### 11.1 Layout

```
┌─────────────────────────────────────────────────────────────┐
│ GeoDemand      [date range slider]  [category ▾]  [privacy ▢]│
├──────────────────────────────────────┬──────────────────────┤
│                                      │ Top zones            │
│           MAP (MapLibre)             │  1. ▲ 39%  1,840     │
│        + deck.gl hex layer           │  2. ▲ 12%  1,310     │
│                                      │  ...                 │
│                                      ├──────────────────────┤
│   legend ▓▓▓▓▓                       │ Zone detail          │
│                                      │  hour-of-day chart   │
└──────────────────────────────────────┴──────────────────────┘
```

### 11.2 Behaviour

- On map idle (debounced about 250 ms), request `/cells` with the new bbox and zoom.
- Cancel in-flight requests when a newer one starts (`AbortController`).
- Colour scale: log or quantile, with a legend and a count tooltip on hover.
- Clicking a hex or a ranked zone selects it, flies the map to it, and loads `/zones/{h3}/hourly`.
- Show a loading state and a "no data / suppressed for privacy" empty state.
- **Privacy mode demo:** a static before/after comparison (raw points vs. hexes) on the demo dataset only.
  The live API never serves raw points.

### 11.3 State

Local React state is enough: `{viewport, timeRange, category, selectedZone}` plus fetched data.
Avoid heavy state libraries.

---

## 12. Benchmark plan

### 12.1 Objectives

Prove the speed claims with before/after numbers, and make the methodology reproducible.

### 12.2 Environment

Record: CPU, RAM, OS, Postgres and Redis versions, Docker resource limits, dataset size and seed.

### 12.3 Configurations

| Config | Description |
|---|---|
| B0 | **Baseline:** raw events table (benchmark-only DB, includes lat/lng), on-the-fly H3/bbox aggregation |
| B1 | Hourly rollup table, no secondary indexes |
| B2 | Hourly rollup + indexes |
| B3 | B2 + Redis cache, **cold** |
| B4 | B2 + Redis cache, **warm** |

B0 exists only in the benchmark environment so the comparison is fair. The production design never stores raw points.

### 12.4 Workload

- Randomised requests: bbox centres sampled around hotspots, zoom 8–15, time ranges (1 h, 1 day, 7 days, 30 days), categories.
- Concurrency levels: 10, 50, 100 users.
- Fixed random seed, with a warm-up phase excluded from results.
- Duration of at least 60 s per configuration and level.

### 12.5 Metrics

| Metric | Source |
|---|---|
| p50 / p95 / p99 latency | Load tool |
| Throughput (req/s) | Load tool |
| Error rate | Load tool |
| Cache hit ratio | `X-Cache` header counts |
| Ingest throughput (events/s) | Ingest timer |
| Storage: raw vs. rollup size | `pg_total_relation_size` |
| Query plans | `EXPLAIN (ANALYZE, BUFFERS)` before and after indexes |

### 12.6 Output

`bench/results.md` containing the environment, a results table per concurrency level, a latency chart,
and a short analysis of what each optimisation contributed. Resume claims must come directly from this file.

### 12.7 Stretch

Scale ingestion and queries to 10M events offline and report how latency and storage grow.

---

## 13. Testing strategy

| Area | Test |
|---|---|
| H3 | Same point → same cell. Parent of a child equals the expected parent. |
| Validation | Each rejection reason triggers. Rejected events leave no coordinates behind. |
| Privacy (storage) | Schema assertion: no persisted column holds event lat/lng. |
| Privacy (serving) | Cells below K are never returned. Threshold applies to the noisy value. |
| Noise | Deterministic for the same `(cell, window, category)`. Differs across windows. |
| Ingest | Batch totals preserved. Duplicate `batch_id` skipped. Failure rolls back cleanly. |
| Rollup | Daily total equals the sum of hourly rows. Re-running gives the same result (idempotent). |
| Cache | Same normalised params → HIT. Version bump → MISS. Redis down → still correct. |
| API | Param validation, 422 cases, response shape, response size cap. |
| Zoom mapping | Each zoom range maps to the expected resolution and source table. |
| End-to-end | Seed a small dataset, query, and assert known hotspot cells rank at the top. |

CI runs lint and tests on every push (GitHub Actions) with Postgres and Redis as service containers.

---

## 14. Security and operations

### 14.1 Security

- Parameterised SQL only (no string-built queries).
- API uses a **read-only** database role. The ingestion/worker role has write access.
- `POST /events/batch` requires an API key (header `X-API-Key`), and the key lives in an environment variable.
- Strict input validation through Pydantic, with caps on bbox size, time range, `limit`, and batch size.
- CORS restricted to the frontend origin.
- Optional basic rate limiting on public endpoints.
- No secrets in the repository. Provide `.env.example`.

### 14.2 Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection |
| `REDIS_URL` | Redis connection |
| `PRIVACY_K` | Minimum count (default 5) |
| `PRIVACY_EPSILON` | Noise parameter, 0 disables noise |
| `PRIVACY_SALT` | Secret for deterministic noise |
| `CACHE_TTL_SECONDS` | Cache expiry |
| `MAX_CELLS` | Response cap (default 5000) |
| `INGEST_API_KEY` | Key for `/events/batch` |
| `ALLOWED_ORIGIN` | CORS origin |

### 14.3 Observability

- Structured JSON logs (request id, route, duration, cache status, cells returned).
- `X-Cache` and `X-Query-Time-Ms` response headers.
- `/health` endpoint.
- Optional Prometheus metrics endpoint.

---

## 15. Deployment

### 15.1 Local

```
cp .env.example .env
docker compose up -d --build
make seed        # generate 1M events and ingest
# open http://localhost:5173 (or :8000)
```

### 15.2 Live demo

| Component | Option (verify current free-tier limits) |
|---|---|
| API + worker | Render / Railway / Fly.io |
| Postgres | Neon / Supabase |
| Redis | Upstash |
| Frontend | Served by the API as static files, or Vercel/Netlify |

Steps:

1. Seed locally, then export the **rollup tables only** (`pg_dump` of `demand_cells`, `demand_daily`)
   and restore them into the hosted database. This keeps raw data off the server entirely.
2. Deploy the API with environment variables set.
3. Build the frontend with the production API URL.
4. Smoke test: `/health`, `/meta`, `/cells`.
5. Note possible cold-start delay in the README, or add a keep-alive ping before demos.

### 15.3 Basemap

Use MapLibre's demo style for development. For the public demo, use a tile provider with a free tier and follow
its terms. Don't load the public OpenStreetMap tile servers from a deployed app.

---

## 16. Repository layout

```
geodemand/
├── docker-compose.yml
├── Makefile                 # seed, test, bench, lint
├── .env.example
├── README.md
├── implementation.md
├── sql/
│   └── schema.sql
├── api/
│   ├── main.py              # FastAPI app and routes
│   ├── config.py            # env settings
│   ├── db.py                # pool, queries
│   ├── cache.py             # key building, get/set, version
│   ├── privacy.py           # noise + K-suppression
│   ├── zoom.py              # zoom → res/source mapping
│   └── schemas.py           # Pydantic models
├── ingest/
│   ├── generate.py          # synthetic data
│   ├── validate.py
│   ├── transform.py         # H3, drop coords, multi-res rollups
│   ├── load.py              # COPY + upsert + batch log
│   ├── rollup.py            # daily rollup job + scheduler
│   └── stream_consumer.py   # optional Redis Streams consumer
├── bench/
│   ├── baseline.py          # raw-events benchmark DB
│   ├── load_test.py         # Locust / asyncio load script
│   └── results.md
├── web/                     # React + Vite + deck.gl app
├── tests/
│   ├── test_h3.py
│   ├── test_privacy.py
│   ├── test_ingest.py
│   ├── test_rollup.py
│   ├── test_cache.py
│   └── test_api.py
└── .github/workflows/ci.yml
```

---

## 17. Milestones and acceptance criteria

| # | Milestone | Days | Acceptance criteria |
|---|---|---|---|
| M1 | Foundation | 1–2 | Compose brings up Postgres and Redis. Schema applied. Generator produces 1M reproducible events. |
| M2 | Ingestion + privacy core | 3–4 | Batches ingest with validation, H3, coordinate drop, multi-res rollups, idempotency. Tests pass. |
| M3 | API | 5–6 | `/cells`, `/top-zones`, `/zones/{h3}/hourly`, `/meta`, `/health` work. K-suppression and noise active. |
| M4 | Caching + rollups | 7–8 | Redis cache with versioned keys. Daily rollup job running. `X-Cache` header visible. |
| M5 | Frontend | 9–11 | Map with hex layer, filters, top-zones sidebar, zone chart, legend. |
| M6 | Benchmarks | 12–13 | All five configurations measured. `results.md` written with real numbers. |
| M7 | Ship | 14–15 | Live demo deployed. README complete. Demo video recorded. CI green. |
| M8 | Stretch | after | Streaming simulation, forecasting, 10M-event run. |

Do not start M5 polish before M6 benchmarks have run once. A basic UI is enough to measure against.

---

## 18. Risks and limitations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope creep into UI polish | Delays the measurable core | Benchmarks before polish |
| h3 v3/v4 API confusion | Wasted time | Pin `h3>=4` and follow the v4 names |
| Double counting (ingest adds vs. rollup overwrites) | Wrong numbers | Dedicated tests, idempotent rollups |
| Misleading benchmarks (warm numbers only) | Credibility loss | Report cold and warm separately, publish method |
| Free-tier cold starts or limits | Weak demo | Keep-alive, small rollup-only dataset, check limits early |
| Overstating privacy | Credibility loss | State the threat model and limitations plainly |
| Bbox over the antimeridian or poles | Wrong results | Documented limitation, validate bbox |
| Synthetic data looks fake | Weak demo | Hotspots, time patterns, anomaly injection |

**Known limitations to document:** not formally differentially private, synthetic data only, single
region assumption, no authentication beyond an ingest API key, no antimeridian support.

---

## 19. Definition of done

- [ ] 1M synthetic events ingested through the real pipeline
- [ ] No persisted table contains event coordinates (test enforced)
- [ ] K-suppression and deterministic noise verified by tests
- [ ] All endpoints implemented, validated, and documented at `/docs`
- [ ] Redis caching with versioned invalidation, and `X-Cache` visible
- [ ] Hourly to daily rollup job running on a schedule
- [ ] Dashboard with map, filters, ranking, and zone detail
- [ ] Benchmarks B0 to B4 run, with `bench/results.md` and the methodology published
- [ ] CI passing (lint and tests)
- [ ] Fresh clone runs with `docker compose up` and `make seed`
- [ ] Live demo URL and a 1–2 minute demo video
- [ ] README with the architecture diagram, privacy design, limitations, and benchmark headline numbers
- [ ] Resume bullets written using only measured numbers
