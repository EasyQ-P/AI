"""7.4.12~7.4.14 평가 · 비교 (T-09, T-10). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["evaluations"])


@router.post("/evaluations")
async def create_evaluation() -> dict:
    """7.4.12 모델 평가 (T-09)"""
    raise not_implemented("7.4.12")


@router.get("/evaluations/{evaluation_id}")
async def get_evaluation(evaluation_id: str) -> dict:
    """7.4.13 평가 결과 (T-09)"""
    raise not_implemented("7.4.13")


@router.post("/comparisons")
async def compare_versions() -> dict:
    """7.4.14 두 버전 비교 (T-10)"""
    raise not_implemented("7.4.14")
