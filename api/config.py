import os
from functools import lru_cache

from api.env import load_local_env


class ApiConfigError(RuntimeError):
    pass


class ApiConfig:
    def __init__(self):
        load_local_env()
        self.app_env = (
            os.environ.get("APP_ENV")
            or os.environ.get("ENVIRONMENT")
            or "development"
        ).strip().lower()
        self.is_production = self.app_env in {"production", "prod"}
        self.jwt_secret = self._required("JWT_SECRET")
        self.jwt_expiry_days = int(os.environ.get("JWT_EXPIRY_DAYS", "30"))
        self.api_host = os.environ.get("API_HOST", "0.0.0.0").strip() or "0.0.0.0"
        self.api_port = int(os.environ.get("API_PORT", "8001"))
        self.cors_allowed_origins = self._resolve_cors_origins()

    def _resolve_cors_origins(self):
        configured = self._csv("CORS_ALLOWED_ORIGINS")
        if configured:
            return configured

        # Local / lower environments: allow Expo web + device clients without extra setup.
        if not self.is_production:
            return ["*"]

        return []

    @staticmethod
    def _required(name):
        value = os.environ.get(name)
        if not value:
            raise ApiConfigError(f"{name} is required.")
        return value

    @staticmethod
    def _csv(name):
        value = os.environ.get(name, "")
        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]


@lru_cache(maxsize=1)
def get_config():
    return ApiConfig()
