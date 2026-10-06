import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env if present
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/geodemand")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

PRIVACY_K = int(os.getenv("PRIVACY_K", "5"))
PRIVACY_EPSILON = float(os.getenv("PRIVACY_EPSILON", "1.0"))
PRIVACY_SALT = os.getenv("PRIVACY_SALT", "geodemand-privacy-salt-change-in-production")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
MAX_CELLS = int(os.getenv("MAX_CELLS", "5000"))

INGEST_API_KEY = os.getenv("INGEST_API_KEY", "geodemand-dev-ingest-key")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
