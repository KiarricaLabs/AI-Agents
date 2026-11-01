import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = os.getenv("PAT_DB_PATH", str(DATA_DIR / "pat.db"))

AI_PROVIDER = os.getenv("PAT_AI_PROVIDER", "ollama")
AI_MODEL = os.getenv("PAT_AI_MODEL", "llama3.1")
AI_BASE_URL = os.getenv("PAT_AI_BASE_URL", "http://localhost:11434")
AI_API_KEY = os.getenv("PAT_AI_API_KEY", "")

MASTER_KEY = os.getenv("PAT_MASTER_KEY", "")  # Fernet key; required for credentials
DEFAULT_TENANT = os.getenv("PAT_DEFAULT_TENANT", "local")

# Local development identity (trusted, server-side, config-supplied).
# When enabled and no valid token is presented, requests run as this identity.
# Set PAT_LOCAL_MODE=0 (or "false") to require authenticated tokens (fail-closed).
LOCAL_MODE = os.getenv("PAT_LOCAL_MODE", "1").strip().lower() in ("1", "true", "yes", "on")
LOCAL_USER = os.getenv("PAT_LOCAL_USER", "local")