"""추론 인터페이스모듈 — T-13(적재), T-18(판정), T-19(상태). 담당: 최의찬, 신재우(연동)."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ServingState:
    mode: str = "LLM_ONLY"            # CUSTOM / LLM_ONLY
    serving_version: Optional[str] = None
    threshold: Optional[float] = None
    loaded: bool = False
    gpu_busy: bool = False


_STATE = ServingState()


def serving_state() -> ServingState:
    return _STATE


def load_model(model_version: str):
    """서빙 버전의 fp16 모델을 GPU에 올린다 (기존 모델과 나란히 적재 → 시험 질문 5건 점검 → 교체)."""
    raise NotImplementedError


def score(question: str, evidences: list[str]) -> list[float]:
    """질문 + 근거 후보(최대 20개) → 근거별 점수 (T-18, 7.4.26)."""
    raise NotImplementedError
