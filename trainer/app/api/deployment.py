"""7.4.21~7.4.23 서빙 전환 · 롤백 (T-13, T-14). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["deployment"])


@router.get("/deployment")
async def get_deployment() -> dict:
    """7.4.21 현재 서빙 설정 (T-13)"""
    raise not_implemented("7.4.21")


@router.put("/deployment")
async def switch_deployment() -> dict:
    """7.4.22 서빙 버전 전환 (T-13)"""
    raise not_implemented("7.4.22")


@router.post("/rollbacks")
async def rollback() -> dict:
    """7.4.23 롤백 (T-14)"""
    raise not_implemented("7.4.23")
