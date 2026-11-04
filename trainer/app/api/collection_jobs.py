"""7.4.6 데이터 재수집 (T-04). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["collection-jobs"])


@router.post("/collection-jobs")
async def create_collection_job() -> dict:
    """7.4.6 데이터 재수집 (T-04)"""
    raise not_implemented("7.4.6")
