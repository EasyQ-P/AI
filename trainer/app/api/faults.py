"""7.4.27 장애 기록 조회 (T-21). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["faults"])


@router.get("/faults")
async def list_faults() -> dict:
    """7.4.27 장애 기록 조회 (T-21)"""
    raise not_implemented("7.4.27")
