"""7.4.2~7.4.5 데이터셋 (T-01~T-03)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Code, TrainerError, not_implemented, ok
from app.core.timefmt import to_kst_iso
from app.db import get_session
from app.db.models import RegDataset, RegTestSet

router = APIRouter(tags=["datasets"])


@router.post("/datasets")
async def register_dataset() -> dict:
    """7.4.2 데이터셋 버전 등록 (T-01)"""
    raise not_implemented("7.4.2")


@router.get("/datasets")
def list_datasets(
    session: Annotated[Session, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """7.4.3 데이터셋 버전 목록 (T-02)"""
    total_count = session.scalar(select(func.count()).select_from(RegDataset)) or 0
    rows = session.execute(
        select(RegDataset, RegTestSet.test_use_count)
        .join(RegTestSet, RegDataset.test_set_version == RegTestSet.test_set_version)
        .order_by(RegDataset.created_at.desc(), RegDataset.dataset_version.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    datasets = [
        {
            "dataset_version": dataset.dataset_version,
            "parent_version": dataset.parent_version,
            "status": dataset.status,
            "contains_aihub": dataset.contains_aihub,
            "statistics": dataset.statistics,
            "script_version": dataset.script_version,
            "retrieval_config_version": dataset.retrieval_config_version,
            "test_set_version": dataset.test_set_version,
            "test_use_count": test_use_count,
            "change_note": dataset.change_note,
            "created_at": to_kst_iso(dataset.created_at),
        }
        for dataset, test_use_count in rows
    ]
    return ok({"datasets": datasets, "total_count": total_count})


@router.get("/datasets/{dataset_version}")
def get_dataset(dataset_version: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    """7.4.4 데이터셋 상세 (T-02)"""
    row = session.execute(
        select(RegDataset, RegTestSet.test_use_count)
        .join(RegTestSet, RegDataset.test_set_version == RegTestSet.test_set_version)
        .where(RegDataset.dataset_version == dataset_version)
    ).first()
    if row is None:
        raise TrainerError(Code.NOT_FOUND, f"dataset not found: {dataset_version}")
    dataset, test_use_count = row
    return ok({
        "dataset_version": dataset.dataset_version,
        "statistics": dataset.statistics,
        "courses_by_split": dataset.courses_by_split,
        "gold_in_candidates_rate": dataset.gold_in_candidates_rate,
        "validation_set_version": dataset.validation_set_version,
        "test_set_version": dataset.test_set_version,
        "eval_slide_version": dataset.eval_slide_version,
        "test_use_count": test_use_count,
        "contains_aihub": dataset.contains_aihub,
        "script_version": dataset.script_version,
        "retrieval_config_version": dataset.retrieval_config_version,
        "change_note": dataset.change_note,
        "storage_uri": dataset.storage_uri,
    })


@router.post("/datasets/{dataset_version}/reviewed-labels")
async def merge_reviewed_labels(dataset_version: str) -> dict:
    """7.4.5 검수 라벨 병합 (T-03)"""
    raise not_implemented("7.4.5")
