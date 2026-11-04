"""7.4.16~7.4.20 모델 버전 (T-12, T-15, T-16). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["models"])


@router.post("/models")
async def register_model() -> dict:
    """7.4.16 모델 버전 등록 (T-12)"""
    raise not_implemented("7.4.16")


@router.get("/models")
async def list_models() -> dict:
    """7.4.17 모델 버전 목록 (T-15)"""
    raise not_implemented("7.4.17")


@router.get("/models/{model_version}")
async def get_model(model_version: str) -> dict:
    """7.4.18 모델 버전 상세 (T-15)"""
    raise not_implemented("7.4.18")


@router.patch("/models/{model_version}")
async def update_model_memo(model_version: str) -> dict:
    """7.4.19 버전 메모 수정 (T-16)"""
    raise not_implemented("7.4.19")


@router.delete("/models/{model_version}")
async def delete_model(model_version: str) -> dict:
    """7.4.20 버전 삭제 (T-16)"""
    raise not_implemented("7.4.20")
