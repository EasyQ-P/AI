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
    # 비우면 {data_root}/registry/registry.db SQLite 파일(학과 서버 규칙상 DB 서버를 띄우지 않는다).
    # PostgreSQL · RDS로 옮길 때는 이 값만 바꾼다. 예: postgresql+psycopg://user:pw@host:5432/easyq_registry
    registry_db_url: str = ""
    data_root: Path = Path("/data/easyq")
    trainer_host: str = "127.0.0.1"
    trainer_port: int = 8000
    # 판정 추론 프로세스 (학습과 분리, 내부 전용)
    inference_host: str = "127.0.0.1"
    inference_port: int = 8001
    judge_timeout_ms: int = 800

    @property
    def registry_url(self) -> str:
        """실제로 접속할 레지스트리 DB 주소."""
        if self.registry_db_url:
            return self.registry_db_url
        return f"sqlite:///{(self.data_root / 'registry' / 'registry.db').as_posix()}"

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
