import os
from pathlib import Path
import pytest

from api.env import _load_env_file, get_database_target_info, load_local_env


def test_load_env_file_basic(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("TEST_KEY_A=value_a\nTEST_KEY_B='value_b'\nTEST_KEY_C=\"value_c\"\n# comment\n", encoding="utf-8")

    # Clean test keys
    for k in ["TEST_KEY_A", "TEST_KEY_B", "TEST_KEY_C"]:
        os.environ.pop(k, None)

    assert _load_env_file(env_file) is True
    assert os.environ.get("TEST_KEY_A") == "value_a"
    assert os.environ.get("TEST_KEY_B") == "value_b"
    assert os.environ.get("TEST_KEY_C") == "value_c"


def test_load_env_file_override_behavior(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("TEST_KEY_OVERRIDE=from_file\n", encoding="utf-8")

    # When override=False, pre-existing environment key is preserved
    os.environ["TEST_KEY_OVERRIDE"] = "pre_existing"
    _load_env_file(env_file, override=False)
    assert os.environ["TEST_KEY_OVERRIDE"] == "pre_existing"

    # When override=True, file value overwrites
    _load_env_file(env_file, override=True)
    assert os.environ["TEST_KEY_OVERRIDE"] == "from_file"


def test_load_local_env_dev_takes_precedence_over_prod(tmp_path, monkeypatch):
    dev_file = tmp_path / ".env.development"
    prod_file = tmp_path / ".env"

    dev_file.write_text(
        "SUPABASE_DB_URL=postgresql://postgres.mwoujuwtwglxagqtnbhj:pass@aws-1.supabase.com:6543/postgres\n"
        "JWT_SECRET=dev_secret\n"
        "APP_ENV=development\n",
        encoding="utf-8"
    )
    prod_file.write_text(
        "SUPABASE_DB_URL=postgresql://postgres.biesaxrexkphyiyrmhcn:pass@aws-1.supabase.com:6543/postgres\n"
        "JWT_SECRET=prod_secret\n"
        "API_PORT=8001\n",
        encoding="utf-8"
    )

    monkeypatch.setattr("api.env._PROJECT_ROOT", tmp_path)

    # Clean keys
    for k in ["SUPABASE_DB_URL", "JWT_SECRET", "APP_ENV", "API_PORT"]:
        os.environ.pop(k, None)

    load_local_env(override=True)

    # Values in .env.development win
    assert "mwoujuwtwglxagqtnbhj" in os.environ["SUPABASE_DB_URL"]
    assert os.environ["JWT_SECRET"] == "dev_secret"
    assert os.environ["APP_ENV"] == "development"

    # Keys only in .env fall back properly
    assert os.environ["API_PORT"] == "8001"


def test_load_local_env_prod_only_when_dev_missing(tmp_path, monkeypatch):
    prod_file = tmp_path / ".env"
    prod_file.write_text(
        "SUPABASE_DB_URL=postgresql://postgres.biesaxrexkphyiyrmhcn:pass@aws-1.supabase.com:6543/postgres\n"
        "JWT_SECRET=prod_secret\n",
        encoding="utf-8"
    )

    monkeypatch.setattr("api.env._PROJECT_ROOT", tmp_path)

    for k in ["SUPABASE_DB_URL", "JWT_SECRET"]:
        os.environ.pop(k, None)

    load_local_env(override=True)

    assert "biesaxrexkphyiyrmhcn" in os.environ["SUPABASE_DB_URL"]
    assert os.environ["JWT_SECRET"] == "prod_secret"


def test_get_database_target_info():
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres.mwoujuwtwglxagqtnbhj:secret_password@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"

    info = get_database_target_info()
    assert info["configured"] is True
    assert info["project_ref"] == "mwoujuwtwglxagqtnbhj"
    assert info["host"] == "aws-1-ap-south-1.pooler.supabase.com"
    assert info["port"] == 6543
    assert info["dbname"] == "postgres"
    assert info["user"] == "postgres.mwoujuwtwglxagqtnbhj"
    # Password must not be leaked in target info
    assert "secret_password" not in str(info.values())
