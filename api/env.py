import os
import re
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(env_path: Path, override: bool = False) -> bool:
    """Load a single .env file. If override is False, keys already in os.environ are preserved."""
    if not env_path.exists():
        return False

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if not override and key in os.environ:
            continue

        os.environ[key] = value.strip().strip('"').strip("'")

    return True


def load_local_env(override: bool = False) -> None:
    """Load environment variables for local development.

    Resolution order (first file's values win for each key):
      1. .env.development  — local dev credentials (git-ignored)
      2. .env              — fallback / production credentials

    On Cloud Run / production there is no .env.development, so only .env
    (or container-injected environment variables) takes effect.
    """
    dev_path = _PROJECT_ROOT / ".env.development"
    prod_path = _PROJECT_ROOT / ".env"

    if dev_path.exists():
        # Load .env.development first (with override if requested)
        _load_env_file(dev_path, override=override)
        # Load .env as fallback for any keys not defined in .env.development
        _load_env_file(prod_path, override=False)
    else:
        _load_env_file(prod_path, override=override)


def get_database_target_info() -> dict[str, str | int | None]:
    """Extract non-sensitive database target metadata (host, port, dbname, user, project_ref)."""
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL") or ""
    if not db_url:
        return {
            "configured": False,
            "host": None,
            "port": None,
            "dbname": None,
            "user": None,
            "project_ref": None,
        }

    try:
        parsed = urlparse(db_url)
        username = parsed.username or ""
        host = parsed.hostname or ""
        port = parsed.port or 5432
        dbname = parsed.path.lstrip("/") or "postgres"

        project_ref = None
        if username.startswith("postgres."):
            project_ref = username.split("postgres.", 1)[1]
        elif host:
            m = re.search(r"([a-z0-9]+)\.(?:supabase|pooler)", host)
            if m:
                project_ref = m.group(1)

        return {
            "configured": True,
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": username,
            "project_ref": project_ref,
        }
    except Exception:
        return {
            "configured": True,
            "host": "unknown",
            "port": None,
            "dbname": "unknown",
            "user": "unknown",
            "project_ref": "unknown",
        }

