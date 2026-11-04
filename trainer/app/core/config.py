from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trainer_api_key: str = "change-me"
    registry_db_url: str = "postgresql+psycopg://easyq:easyq_dev@localhost:5433/easyq_registry"
    data_root: Path = Path("/data/easyq")
    trainer_host: str = "127.0.0.1"
    trainer_port: int = 8000
    judge_timeout_ms: int = 800


@lru_cache
def get_settings() -> Settings:
    return Settings()
