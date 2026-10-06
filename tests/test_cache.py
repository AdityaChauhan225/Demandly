from api.cache import cache_manager


def test_cache_normalisation_and_hits():
    params1 = {
        "res": 8,
        "w": 77.59,
        "s": 12.97,
        "e": 77.65,
        "n": 13.01,
        "from": "2026-09-01T12:00:00Z",
        "to": "2026-09-01T14:00:00Z",
        "category": "food"
    }

    # Same logical params, different insertion order
    params2 = {
        "category": "food",
        "to": "2026-09-01T14:00:00Z",
        "from": "2026-09-01T12:00:00Z",
        "n": 13.01,
        "e": 77.65,
        "s": 12.97,
        "w": 77.59,
        "res": 8
    }

    key1 = cache_manager.build_cache_key("cells", params1)
    key2 = cache_manager.build_cache_key("cells", params2)

    assert key1 == key2, "Deterministically normalised params must produce identical cache keys"

    # Set value
    test_val = {"cells": [{"h3": "88283082a1fffff", "count": 42}]}
    cache_manager.set(key1, test_val, ttl=60)

    # Get value (Cache HIT)
    retrieved = cache_manager.get(key1)
    assert retrieved == test_val

def test_version_bump_invalidates_cache():
    params = {"res": 7, "from": "2026-09-01T00:00:00Z", "to": "2026-09-02T00:00:00Z"}
    old_key = cache_manager.build_cache_key("cells", params)

    cache_manager.set(old_key, {"result": "old_data"}, ttl=60)
    assert cache_manager.get(old_key) is not None

    # Bump version
    cache_manager.increment_data_version()

    new_key = cache_manager.build_cache_key("cells", params)
    assert new_key != old_key, "Version bump must alter the cache key prefix"
    # New key must be a MISS
    assert cache_manager.get(new_key) is None
