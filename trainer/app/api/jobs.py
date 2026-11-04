"""7.4.24~7.4.25 작업 조회 (T-17). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
async def list_jobs() -> dict:
    """7.4.24 작업 목록 (T-17)"""
    raise not_implemented("7.4.24")


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    """7.4.25 작업 상태 (T-17)"""
    raise not_implemented("7.4.25")
