import hashlib
import json
import logging
import time
from typing import Any

import redis

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

from api.config import CACHE_TTL_SECONDS, REDIS_URL

logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_url = redis_url
        self._client: redis.Redis | None = None
        self._fake_client: Any | None = None
        self._last_connect_attempt = 0.0
        self._connect_retry_delay = 30.0  # seconds between redis reconnection attempts

    def get_client(self) -> Any:
        # If real client exists and is connected
        if self._client is not None:
            return self._client

        now = time.time()
        # Avoid hammering connection attempts on every single request
        if now - self._last_connect_attempt > self._connect_retry_delay:
            self._last_connect_attempt = now
            try:
                client = redis.Redis.from_url(
                    self.redis_url,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                    decode_responses=True
                )
                client.ping()
                self._client = client
                logger.info("Successfully connected to Redis instance")
                return self._client
            except Exception:
                logger.info(f"Redis not reachable at {self.redis_url}, using high-performance in-memory cache/fakeredis")

        # Fallback to fakeredis or in-memory
        if self._fake_client is None:
            if HAS_FAKEREDIS:
                self._fake_client = fakeredis.FakeRedis(decode_responses=True)
            else:
                self._fake_client = None
        return self._fake_client

    def get_data_version(self) -> int:
        client = self.get_client()
        if client:
            try:
                val = client.get("data_version")
                if val is not None:
                    return int(val)
                client.set("data_version", 1)
                return 1
            except Exception as e:
                logger.warning(f"Error reading data_version: {e}")
        return 1

    def increment_data_version(self) -> int:
        client = self.get_client()
        if client:
            try:
                return client.incr("data_version")
            except Exception as e:
                logger.warning(f"Error incrementing data_version: {e}")
        return 2

    def build_cache_key(self, prefix: str, params: dict) -> str:
        version = self.get_data_version()
        norm_str = json.dumps(params, sort_keys=True, separators=(",", ":"))
        param_hash = hashlib.sha1(norm_str.encode("utf-8")).hexdigest()
        return f"{prefix}:v{version}:{param_hash}"

    def get(self, key: str) -> Any | None:
        client = self.get_client()
        if client:
            try:
                data = client.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Cache get error for {key}: {e}")
        return None

    def set(self, key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
        client = self.get_client()
        if client:
            try:
                serialized = json.dumps(value)
                client.set(key, serialized, ex=ttl)
            except Exception as e:
                logger.warning(f"Cache set error for {key}: {e}")

cache_manager = CacheManager()
