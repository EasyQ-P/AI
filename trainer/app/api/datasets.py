"""7.4.2~7.4.5 데이터셋 (T-01~T-03). 뼈대만 있다: 경로와 함수 이름은 7.4 그대로, 내용은 구현 전."""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["datasets"])


@router.post("/datasets")
async def register_dataset() -> dict:
    """7.4.2 데이터셋 버전 등록 (T-01)"""
    raise not_implemented("7.4.2")


@router.get("/datasets")
async def list_datasets() -> dict:
    """7.4.3 데이터셋 버전 목록 (T-02)"""
    raise not_implemented("7.4.3")


@router.get("/datasets/{dataset_version}")
async def get_dataset(dataset_version: str) -> dict:
    """7.4.4 데이터셋 상세 (T-02)"""
    raise not_implemented("7.4.4")


@router.post("/datasets/{dataset_version}/reviewed-labels")
async def merge_reviewed_labels(dataset_version: str) -> dict:
    """7.4.5 검수 라벨 병합 (T-03)"""
    raise not_implemented("7.4.5")
