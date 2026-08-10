"""Run the Money Vault API for local / lower-environment testing.

Binds to 0.0.0.0 so Android emulators and physical devices on the same Wi-Fi
can reach the service (not just localhost).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from api.config import get_config
from api.env import load_local_env


def main() -> None:
    load_local_env()
    os.environ.setdefault("APP_ENV", "development")
    get_config.cache_clear()
    config = get_config()

    host = os.environ.get("API_HOST", config.api_host)
    port = int(os.environ.get("API_PORT", str(config.api_port)))

    print(f"Starting Money Vault API ({config.app_env}) on http://{host}:{port}")
    print("Health: http://127.0.0.1:{0}/health".format(port))
    print("Docs:   http://127.0.0.1:{0}/docs".format(port))
    print("Phone/emulator clients must use your LAN IP or 10.0.2.2, not 127.0.0.1.")

    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=not config.is_production,
        reload_dirs=[str(ROOT)] if not config.is_production else None,
    )


if __name__ == "__main__":
    main()
