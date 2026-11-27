from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_API_KEY = "change-me"
# 레포 루트(trainer/app/core/config.py 기준 세 단계 위). 작업 프로세스는 trainer/에서 돌기 때문에
# .env와 상대 경로를 현재 폴더가 아니라 이 위치 기준으로 읽는다.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # dev: 로컬 개발(기본 키 허용) / prod: 학과 서버(키가 없거나 기본값이면 시작 거부)
    trainer_env: Literal["dev", "prod"] = "prod"
    trainer_api_key: str = ""
    # 비우면 {data_root}/registry/registry.db SQLite 파일(학과 서버 규칙상 DB 서버를 띄우지 않는다).
    # PostgreSQL · RDS로 옮길 때는 이 값만 바꾼다. 예: postgresql+psycopg://user:pw@host:5432/easyq_registry
    registry_db_url: str = ""
    data_root: Path = Path("/home/t26112/easyq-data")  # 학과 서버(/data 없음, design-changes 4번)
    trainer_host: str = "127.0.0.1"
    trainer_port: int = 8000
    # 판정 추론 프로세스 (학습과 분리, 내부 전용)
    inference_host: str = "127.0.0.1"
    inference_port: int = 8001
    judge_timeout_ms: int = 800
    # 학과 서버 가이드: GPU는 정해진 한 장만 쓴다. 학습 · 평가 · 변환 작업 프로세스에 CUDA_VISIBLE_DEVICES로 넘긴다.
    gpu_device: str = "0"
    # 작업 프로세스가 남긴 상태 파일을 레지스트리에 옮기는 주기(초)
    job_poll_seconds: float = 2.0

    @field_validator("data_root")
    @classmethod
    def _absolute_data_root(cls, value: Path) -> Path:
        """상대 경로(로컬 ./data/local 등)는 레포 루트 기준으로 바꾼다. API와 작업 프로세스가 같은 폴더를 보게 한다."""
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @property
    def docs_enabled(self) -> bool:
        """API 설명서(/api/v1/docs · openapi.json)는 개발 모드에서만 연다. 학과 서버(prod)에서는 끈다."""
        return self.trainer_env == "dev"

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
