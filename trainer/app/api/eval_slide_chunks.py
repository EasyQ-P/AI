"""7.4.28 평가용 교안 조각 목록 (T-22). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["eval-slide-chunks"])


@router.get("/eval-slide-chunks")
async def list_eval_slide_chunks() -> dict:
    """7.4.28 평가용 교안 조각 목록 (T-22)"""
    raise not_implemented("7.4.28")
