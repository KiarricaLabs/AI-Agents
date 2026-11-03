import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Defensive guard (D4.3 production-readiness): the default DB path is a local,
# disposable dev artifact. If PAT_DB_PATH was not set explicitly, surface a
# warning at import so ad-hoc `import api.app` / migration commands never
# silently migrate/modify the default file. Warning-only — legitimate default-
# path operation (running the app without an override) is unaffected.
_DB_EXPLICIT = "PAT_DB_PATH" in os.environ
DB_PATH = os.getenv("PAT_DB_PATH", str(DATA_DIR / "pat.db"))
if not _DB_EXPLICIT:
    import logging as _logging
    _logging.getLogger("personal_ai_team.settings").warning(
        "PAT_DB_PATH is not set; using the default local DB at %s. This default "
        "path is a disposable dev artifact. Set PAT_DB_PATH to an explicit DB "
        "to avoid accidentally migrating/modifying this file during ad-hoc "
        "imports or migrations.", DB_PATH)

AI_PROVIDER = os.getenv("PAT_AI_PROVIDER", "ollama")
AI_MODEL = os.getenv("PAT_AI_MODEL", "llama3.1")
AI_BASE_URL = os.getenv("PAT_AI_BASE_URL", "http://localhost:11434")
AI_API_KEY = os.getenv("PAT_AI_API_KEY", "")

MASTER_KEY = os.getenv("PAT_MASTER_KEY", "")  # Fernet key; required for credentials
DEFAULT_TENANT = os.getenv("PAT_DEFAULT_TENANT", "local")

# Token-signing secret (raw, unvalidated). See core.auth.resolve_signing_secret()
# for fail-closed resolution, local-mode fallback, and validation rules.
AUTH_SECRET = os.getenv("PAT_AUTH_SECRET", "")

# Local development identity (trusted, server-side, config-supplied).
# When enabled and no valid token is presented, requests run as this identity.
# Set PAT_LOCAL_MODE=0 (or "false") to require authenticated tokens (fail-closed).
LOCAL_MODE = os.getenv("PAT_LOCAL_MODE", "1").strip().lower() in ("1", "true", "yes", "on")
LOCAL_USER = os.getenv("PAT_LOCAL_USER", "local")