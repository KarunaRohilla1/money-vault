import os
from functools import lru_cache

from api.env import load_local_env


class ApiConfigError(RuntimeError):
    pass


class ApiConfig:
    def __init__(self):
        load_local_env()
        self.jwt_secret = self._required("JWT_SECRET")
        self.jwt_expiry_days = int(os.environ.get("JWT_EXPIRY_DAYS", "30"))
        self.cors_allowed_origins = self._csv("CORS_ALLOWED_ORIGINS")

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
