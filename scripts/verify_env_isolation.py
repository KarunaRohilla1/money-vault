"""Verify that the env loading correctly separates dev from prod credentials.

Run from the money-vault project root:
    .venv/Scripts/python.exe scripts/verify_env_isolation.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Clear any previously loaded values so we get a clean test.
KEYS_TO_CHECK = [
    "SUPABASE_DB_URL",
    "JWT_SECRET",
    "APP_ENV",
    "API_HOST",
    "API_PORT",
]

for key in KEYS_TO_CHECK:
    os.environ.pop(key, None)

from api.env import load_local_env  # noqa: E402

load_local_env()

print("=" * 60)
print("Environment Isolation Verification")
print("=" * 60)

env_dev_path = ROOT / ".env.development"
env_path = ROOT / ".env"

print(f"\n.env.development exists: {env_dev_path.exists()}")
print(f".env exists:             {env_path.exists()}")

supabase_url = os.environ.get("SUPABASE_DB_URL", "")
jwt_secret = os.environ.get("JWT_SECRET", "")
app_env = os.environ.get("APP_ENV", "")

# Detect which Supabase project is in use by checking the pooler hostname.
PROD_REF = "biesaxrexkphyiyrmhcn"
is_prod_db = PROD_REF in supabase_url

print(f"\nAPP_ENV:         {app_env}")
print(f"SUPABASE_DB_URL: {supabase_url[:60]}{'...' if len(supabase_url) > 60 else ''}")
print(f"JWT_SECRET:      {jwt_secret[:20]}{'...' if len(jwt_secret) > 20 else ''}")
print(f"\nUsing production Supabase: {is_prod_db}")

errors = []

if not supabase_url:
    errors.append("SUPABASE_DB_URL is empty - fill in .env.development")

if not jwt_secret:
    errors.append("JWT_SECRET is empty - fill in .env.development")

if env_dev_path.exists() and is_prod_db:
    errors.append(
        "WARNING: .env.development exists but SUPABASE_DB_URL still points "
        "to the PRODUCTION Supabase project. Update .env.development with "
        "your dev project credentials."
    )

if env_dev_path.exists() and not is_prod_db and supabase_url:
    print("\n[OK] Local development is using a SEPARATE dev database.")

if not env_dev_path.exists():
    errors.append(
        ".env.development not found. Copy .env.example to .env.development "
        "and fill in your dev Supabase credentials."
    )

if errors:
    print("\n--- Issues ---")
    for error in errors:
        print(f"  [!] {error}")
    sys.exit(1)
else:
    print("\n[OK] All checks passed.")
    sys.exit(0)
