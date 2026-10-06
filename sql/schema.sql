-- Demandly Schema
-- PostgreSQL 16 compatible (and SQLite/DuckDB translatable)

-- Hourly, multi-resolution aggregates (the main serving table)
CREATE TABLE IF NOT EXISTS demand_cells (
  res      SMALLINT         NOT NULL CHECK (res IN (6,7,8,9)),
  h3       TEXT             NOT NULL,
  bucket   TIMESTAMPTZ      NOT NULL,           -- start of the hour, UTC
  category TEXT             NOT NULL,
  cnt      INTEGER          NOT NULL CHECK (cnt >= 0),
  lat_c    DOUBLE PRECISION NOT NULL,           -- cell CENTER (not an event location)
  lng_c    DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (res, h3, bucket, category)
);

CREATE INDEX IF NOT EXISTS demand_cells_res_bucket ON demand_cells (res, bucket);
CREATE INDEX IF NOT EXISTS demand_cells_res_geo    ON demand_cells (res, lat_c, lng_c);

-- Daily rollup, same shape, bucket = start of day (UTC)
CREATE TABLE IF NOT EXISTS demand_daily (
  res      SMALLINT         NOT NULL CHECK (res IN (6,7,8,9)),
  h3       TEXT             NOT NULL,
  bucket   TIMESTAMPTZ      NOT NULL,
  category TEXT             NOT NULL,
  cnt      INTEGER          NOT NULL CHECK (cnt >= 0),
  lat_c    DOUBLE PRECISION NOT NULL,
  lng_c    DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (res, h3, bucket, category)
);

CREATE INDEX IF NOT EXISTS demand_daily_res_bucket ON demand_daily (res, bucket);
CREATE INDEX IF NOT EXISTS demand_daily_res_geo    ON demand_daily (res, lat_c, lng_c);

-- Idempotency + audit for ingested batches
CREATE TABLE IF NOT EXISTS ingest_batches (
  batch_id    TEXT PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  events_in   INTEGER NOT NULL,
  accepted    INTEGER NOT NULL,
  rejected    INTEGER NOT NULL
);

-- Rejected events summarised by reason (no raw coordinates stored)
CREATE TABLE IF NOT EXISTS rejected_summary (
  batch_id TEXT NOT NULL REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
  reason   TEXT NOT NULL,
  n        INTEGER NOT NULL,
  PRIMARY KEY (batch_id, reason)
);
