"""7.4.15 fp16 변환 (T-11). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["export-jobs"])


@router.post("/export-jobs")
async def create_export_job() -> dict:
    """7.4.15 fp16 변환 (T-11)"""
    raise not_implemented("7.4.15")
