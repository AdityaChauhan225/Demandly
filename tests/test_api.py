import uuid

import pytest
from fastapi.testclient import TestClient

from api.config import INGEST_API_KEY
from api.db import init_db
from api.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["postgres"] is True

def test_meta_endpoint():
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    data = response.json()
    assert "categories" in data
    assert "resolutions" in data
    assert "k" in data
    assert data["k"] == 5

def test_batch_ingest_and_auth():
    unique_batch_id = f"test-api-batch-{uuid.uuid4().hex[:8]}"
    payload = {
        "batch_id": unique_batch_id,
        "events": [
            {"lat": 12.9716, "lng": 77.5946, "ts": "2026-09-01T10:00:00Z", "category": "food"},
            {"lat": 12.9720, "lng": 77.5950, "ts": "2026-09-01T10:05:00Z", "category": "food"},
            {"lat": 12.9718, "lng": 77.5948, "ts": "2026-09-01T10:10:00Z", "category": "food"},
            {"lat": 12.9715, "lng": 77.5945, "ts": "2026-09-01T10:15:00Z", "category": "food"},
            {"lat": 12.9717, "lng": 77.5947, "ts": "2026-09-01T10:20:00Z", "category": "food"},
            {"lat": 12.9719, "lng": 77.5949, "ts": "2026-09-01T10:25:00Z", "category": "food"},
        ]
    }

    # 1. Missing / wrong API key
    bad_res = client.post("/api/v1/events/batch", json=payload, headers={"X-API-Key": "wrong-key"})
    assert bad_res.status_code == 401

    # 2. Correct API key
    ok_res = client.post("/api/v1/events/batch", json=payload, headers={"X-API-Key": INGEST_API_KEY})
    assert ok_res.status_code == 200
    res_data = ok_res.json()
    assert res_data["accepted"] == 6
    assert res_data["rejected"] == 0
    assert res_data["duplicate_batch"] is False

    # 3. Duplicate batch
    dup_res = client.post("/api/v1/events/batch", json=payload, headers={"X-API-Key": INGEST_API_KEY})
    assert dup_res.status_code == 200
    assert dup_res.json()["duplicate_batch"] is True

def test_cells_query_and_headers():
    # Cold query
    res = client.get(
        "/api/v1/cells",
        params={
            "bbox": "77.5,12.9,77.7,13.1",
            "zoom": 12,
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-09-02T00:00:00Z"
        }
    )
    assert res.status_code == 200
    assert res.headers.get("X-Cache") in ["HIT", "MISS"]
    assert "X-Query-Time-Ms" in res.headers
    data = res.json()
    assert "cells" in data
    assert "res" in data
    assert data["res"] == 8

    # Warm query
    res_warm = client.get(
        "/api/v1/cells",
        params={
            "bbox": "77.5,12.9,77.7,13.1",
            "zoom": 12,
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-09-02T00:00:00Z"
        }
    )
    assert res_warm.status_code == 200
    assert res_warm.headers.get("X-Cache") == "HIT"

def test_top_zones_endpoint():
    res = client.get(
        "/api/v1/top-zones",
        params={
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-09-02T00:00:00Z",
            "res": 8,
            "limit": 5
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert "window" in data
    assert "previous_window" in data
    assert "zones" in data

def test_zone_hourly_endpoint():
    h3_sample = "88283082a1fffff"
    res = client.get(f"/api/v1/zones/{h3_sample}/hourly")
    assert res.status_code == 200
    data = res.json()
    assert data["h3"] == h3_sample
    assert len(data["hours"]) == 24
    assert "peak_hours" in data

def test_invalid_query_parameters():
    # Inverted from/to
    res = client.get(
        "/api/v1/cells",
        params={
            "bbox": "77.5,12.9,77.7,13.1",
            "zoom": 12,
            "from": "2026-09-02T00:00:00Z",
            "to": "2026-09-01T00:00:00Z"
        }
    )
    assert res.status_code == 422

    # Malformed bbox
    res2 = client.get(
        "/api/v1/cells",
        params={
            "bbox": "not,a,box",
            "zoom": 12,
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-09-02T00:00:00Z"
        }
    )
    assert res2.status_code == 422
