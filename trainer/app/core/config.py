from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_API_KEY = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # dev: 로컬 개발(기본 키 허용) / prod: 학과 서버(키가 없거나 기본값이면 시작 거부)
    trainer_env: Literal["dev", "prod"] = "prod"
    trainer_api_key: str = ""
    registry_db_url: str = "postgresql+psycopg://easyq:easyq_dev@localhost:5433/easyq_registry"
    data_root: Path = Path("/data/easyq")
    trainer_host: str = "127.0.0.1"
    trainer_port: int = 8000
    # 판정 추론 프로세스 (학습과 분리, 내부 전용)
    inference_host: str = "127.0.0.1"
    inference_port: int = 8001
    judge_timeout_ms: int = 800

    @property
    def inference_base_url(self) -> str:
        return f"http://{self.inference_host}:{self.inference_port}"


def check_settings(settings: Settings) -> None:
    """개발 모드가 아니면 API 키가 비었거나 기본값일 때 서버를 시작하지 않는다."""
    if settings.trainer_env != "dev" and settings.trainer_api_key in ("", PLACEHOLDER_API_KEY):
        raise RuntimeError("TRAINER_API_KEY가 없거나 기본값입니다. 학과 서버에서는 실제 키를 넣어야 합니다.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
