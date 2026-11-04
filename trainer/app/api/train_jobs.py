"""7.4.7~7.4.11 학습 · 학습 파라미터 (T-05~T-08). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["train-jobs"])


@router.post("/train-jobs")
async def create_train_job() -> dict:
    """7.4.7 학습 · 재학습 (T-05)"""
    raise not_implemented("7.4.7")


@router.get("/train-jobs/{job_id}")
async def get_train_job(job_id: str) -> dict:
    """7.4.8 학습 진행 · 학습 곡선 (T-06)"""
    raise not_implemented("7.4.8")


@router.delete("/train-jobs/{job_id}")
async def cancel_train_job(job_id: str) -> dict:
    """7.4.9 학습 중단 (T-07)"""
    raise not_implemented("7.4.9")


@router.get("/train-configs/default")
async def get_default_train_config() -> dict:
    """7.4.10 기본 학습 파라미터 조회 (T-08)"""
    raise not_implemented("7.4.10")


@router.put("/train-configs/default")
async def update_default_train_config() -> dict:
    """7.4.11 기본 학습 파라미터 수정 (T-08)"""
    raise not_implemented("7.4.11")
