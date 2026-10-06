import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.cache import cache_manager
from api.config import (
    ALLOWED_ORIGIN,
    CACHE_TTL_SECONDS,
    INGEST_API_KEY,
    MAX_CELLS,
    PRIVACY_EPSILON,
    PRIVACY_K,
)
from api.db import (
    check_db_health,
    get_cells,
    get_meta_info,
    get_top_zones,
    get_zone_hourly,
    init_db,
)
from api.privacy import apply_privacy, apply_zone_privacy
from api.schemas import (
    BatchIngestRequest,
    BatchIngestResponse,
    CellCount,
    CellsResponse,
    HealthResponse,
    MetaResponse,
    ResolutionInfo,
    TopZonesResponse,
    ZoneHourlyResponse,
)
from api.zoom import choose_source_table, parse_and_validate_bbox, zoom_to_resolution
from ingest.load import load_batch
from ingest.transform import transform_events_to_cells
from ingest.validate import validate_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("demandly")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Demandly database schema...")
    try:
        init_db()
    except Exception as e:
        logger.warning(f"Startup DB init warning: {e}")
    yield

app = FastAPI(
    title="Demandly API",
    version="1.0.0",
    description="Privacy-preserving, high-performance geospatial demand analytics platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS configuration
origins = [ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cache", "X-Query-Time-Ms"]
)

@app.get("/health", response_model=HealthResponse)
@app.get("/api/v1/health", response_model=HealthResponse)
def health_check():
    db_ok = check_db_health()
    redis_client = cache_manager.get_client()
    redis_ok = False
    if redis_client:
        try:
            redis_ok = bool(redis_client.ping())
        except Exception:
            redis_ok = False

    status = "healthy" if db_ok else "unhealthy"
    status_code = 200 if db_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "postgres": db_ok,
            "redis": redis_ok,
            "backend_mode": "online"
        }
    )

@app.get("/api/v1/meta", response_model=MetaResponse)
def get_metadata():
    info = get_meta_info()
    resolutions = [
        ResolutionInfo(zoom_range="<= 9", res=6, approx_edge="3.2 km"),
        ResolutionInfo(zoom_range="10 - 11", res=7, approx_edge="1.2 km"),
        ResolutionInfo(zoom_range="12 - 13", res=8, approx_edge="460 m"),
        ResolutionInfo(zoom_range=">= 14", res=9, approx_edge="175 m")
    ]
    return MetaResponse(
        categories=info["categories"],
        time_range=info["time_range"],
        k=PRIVACY_K,
        epsilon=PRIVACY_EPSILON,
        resolutions=resolutions,
        total_cells=info["total_cells"],
        total_events=info["total_events"]
    )

@app.get("/api/v1/cells", response_model=CellsResponse)
def get_demand_cells(
    response: Response,
    bbox: str = Query(..., description="w,s,e,n bounding box coordinates"),
    zoom: float = Query(..., description="Current map zoom level"),
    from_: str = Query(..., alias="from", description="ISO datetime start (inclusive)"),
    to: str = Query(..., description="ISO datetime end (exclusive)"),
    category: str | None = Query(None, description="Optional category filter")
):
    start_time = time.perf_counter()

    # 1. Parse and validate inputs
    w, s, e, n = parse_and_validate_bbox(bbox, zoom)
    try:
        from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ISO datetime format for 'from' or 'to'")

    if from_dt >= to_dt:
        raise HTTPException(status_code=422, detail="'from' must be strictly earlier than 'to'")

    # Zoom -> Resolution and Window -> Table mapping
    res = zoom_to_resolution(zoom)
    source_table = choose_source_table(from_dt, to_dt)

    # 2. Normalise parameters for high cache hit rate (Section 9.2)
    norm_w = round(w, 2)
    norm_s = round(s, 2)
    norm_e = round(e, 2)
    norm_n = round(n, 2)
    norm_from = from_dt.strftime("%Y-%m-%dT%H:00:00Z")
    norm_to = to_dt.strftime("%Y-%m-%dT%H:00:00Z")
    norm_cat = category.strip().lower() if category else "*"

    cache_params = {
        "res": res,
        "source": source_table,
        "w": norm_w,
        "s": norm_s,
        "e": norm_e,
        "n": norm_n,
        "from": norm_from,
        "to": norm_to,
        "category": norm_cat
    }

    cache_key = cache_manager.build_cache_key("cells", cache_params)
    cached_data = cache_manager.get(cache_key)

    if cached_data is not None:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Cache"] = "HIT"
        response.headers["X-Query-Time-Ms"] = str(elapsed_ms)
        return cached_data

    # 3. Query database on cache miss
    raw_cells = get_cells(
        source_table=source_table,
        res=res,
        from_dt=from_dt,
        to_dt=to_dt,
        w=w,
        s=s,
        e=e,
        n=n,
        category=category
    )

    # 4. Apply K-suppression and deterministic Laplace noise (Section 7.3)
    privacy_cells = apply_privacy(
        cells=raw_cells,
        from_ts=norm_from,
        to_ts=norm_to,
        category=category,
        k=PRIVACY_K,
        epsilon=PRIVACY_EPSILON
    )

    # Enforce response cap
    if len(privacy_cells) > MAX_CELLS:
        privacy_cells = privacy_cells[:MAX_CELLS]

    cell_items = [CellCount(h3=c["h3"], count=c["count"]) for c in privacy_cells]

    payload = {
        "res": res,
        "source": "daily" if source_table == "demand_daily" else "hourly",
        "from": from_dt.isoformat(),
        "to": to_dt.isoformat(),
        "cells": [c.model_dump() for c in cell_items],
        "suppressed": True,
        "k": PRIVACY_K
    }

    # Store in Redis
    cache_manager.set(cache_key, payload, ttl=CACHE_TTL_SECONDS)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Query-Time-Ms"] = str(elapsed_ms)
    return payload

@app.get("/api/v1/top-zones", response_model=TopZonesResponse)
def get_top_ranked_zones(
    response: Response,
    from_: str = Query(..., alias="from", description="ISO datetime start"),
    to: str = Query(..., description="ISO datetime end"),
    category: str | None = Query(None, description="Optional category filter"),
    res: int = Query(8, description="H3 resolution (default: 8)"),
    limit: int = Query(10, ge=1, le=50, description="Number of zones to return (max: 50)")
):
    start_time = time.perf_counter()

    try:
        from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ISO datetime format for 'from' or 'to'")

    if from_dt >= to_dt:
        raise HTTPException(status_code=422, detail="'from' must be strictly earlier than 'to'")

    # Compute previous window of equal duration
    duration = to_dt - from_dt
    prev_from_dt = from_dt - duration
    prev_to_dt = from_dt

    source_table = choose_source_table(from_dt, to_dt)
    norm_from = from_dt.strftime("%Y-%m-%dT%H:00:00Z")
    norm_to = to_dt.strftime("%Y-%m-%dT%H:00:00Z")
    norm_cat = category.strip().lower() if category else "*"

    cache_params = {
        "res": res,
        "from": norm_from,
        "to": norm_to,
        "category": norm_cat,
        "limit": limit
    }
    cache_key = cache_manager.build_cache_key("top", cache_params)
    cached_data = cache_manager.get(cache_key)

    if cached_data is not None:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Cache"] = "HIT"
        response.headers["X-Query-Time-Ms"] = str(elapsed_ms)
        return cached_data

    # Overfetch candidates so suppression doesn't starve the limit
    overfetch = min(limit * 3, 100)
    raw_zones = get_top_zones(
        source_table=source_table,
        res=res,
        from_dt=from_dt,
        to_dt=to_dt,
        prev_from_dt=prev_from_dt,
        category=category,
        limit=limit,
        overfetch=overfetch
    )

    # Privacy processing (noise on counts, drop if < K, compute growth)
    privacy_zones = apply_zone_privacy(
        zones=raw_zones,
        from_ts=norm_from,
        to_ts=norm_to,
        category=category,
        k=PRIVACY_K,
        epsilon=PRIVACY_EPSILON
    )

    trimmed_zones = privacy_zones[:limit]

    payload = {
        "window": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
        "previous_window": {"from": prev_from_dt.isoformat(), "to": prev_to_dt.isoformat()},
        "zones": trimmed_zones
    }

    cache_manager.set(cache_key, payload, ttl=CACHE_TTL_SECONDS)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Query-Time-Ms"] = str(elapsed_ms)
    return payload

@app.get("/api/v1/zones/{h3}/hourly", response_model=ZoneHourlyResponse)
def get_zone_hourly_profile(
    h3: str,
    response: Response,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    category: str | None = Query(None)
):
    start_time = time.perf_counter()

    from_dt = None
    to_dt = None
    if from_ and to:
        try:
            from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
            to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid ISO datetime format for 'from' or 'to'")

    norm_from = from_dt.strftime("%Y-%m-%dT%H:00:00Z") if from_dt else "*"
    norm_to = to_dt.strftime("%Y-%m-%dT%H:00:00Z") if to_dt else "*"
    norm_cat = category.strip().lower() if category else "*"

    cache_params = {
        "h3": h3,
        "from": norm_from,
        "to": norm_to,
        "category": norm_cat
    }
    cache_key = cache_manager.build_cache_key("zone", cache_params)
    cached_data = cache_manager.get(cache_key)

    if cached_data is not None:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Cache"] = "HIT"
        response.headers["X-Query-Time-Ms"] = str(elapsed_ms)
        return cached_data

    data = get_zone_hourly(
        h3_cell=h3,
        from_dt=from_dt,
        to_dt=to_dt,
        category=category
    )

    cache_manager.set(cache_key, data, ttl=CACHE_TTL_SECONDS)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Query-Time-Ms"] = str(elapsed_ms)
    return data

@app.post("/api/v1/events/batch", response_model=BatchIngestResponse)
def ingest_batch_events(
    batch: BatchIngestRequest,
    x_api_key: str | None = Header(None, alias="X-API-Key")
):
    # API key check (Section 14.1)
    if INGEST_API_KEY and x_api_key != INGEST_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")

    if len(batch.events) > 10_000:
        raise HTTPException(status_code=422, detail="Batch size exceeds maximum limit of 10,000 events")

    # Convert events list to DataFrame
    event_dicts = [e.model_dump() for e in batch.events]
    df = pd.DataFrame(event_dicts)

    # 1. Validation (Section 5.2)
    valid_df, rejection_counts = validate_events(df)
    events_in = len(df)
    accepted = len(valid_df)
    rejected = events_in - accepted

    # 2 & 3. Transformation & Multi-res bucketing (Section 5.3 & 5.4)
    rollup_df = transform_events_to_cells(valid_df)

    # 4. Load & Idempotency (Section 5.5)
    result = load_batch(
        batch_id=batch.batch_id,
        rollup_df=rollup_df,
        events_in=events_in,
        accepted=accepted,
        rejected=rejected,
        rejection_reasons=rejection_counts
    )

    return BatchIngestResponse(
        accepted=result["accepted"],
        rejected=result["rejected"],
        duplicate_batch=result["duplicate_batch"]
    )

# Static frontend serving if built
web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if web_dist.exists() and (web_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        target = web_dist / full_path
        if target.exists() and target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(web_dist / "index.html"))
