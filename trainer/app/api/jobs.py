"""7.4.24~7.4.25 작업 조회 (T-17)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Code, TrainerError, ok
from app.core.timefmt import to_kst_iso
from app.db import get_session
from app.db.models import JOB_STATUSES, JOB_TYPES, RegJob

router = APIRouter(tags=["jobs"])

JOB_TYPE_PATTERN = "^(?:" + "|".join(JOB_TYPES) + ")$"
JOB_STATUS_PATTERN = "^(?:" + "|".join(JOB_STATUSES) + ")$"


@router.get("/jobs")
def list_jobs(
    session: Annotated[Session, Depends(get_session)],
    job_type: Annotated[Optional[str], Query(alias="type", pattern=JOB_TYPE_PATTERN)] = None,
    status: Annotated[Optional[str], Query(pattern=JOB_STATUS_PATTERN)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """7.4.24 작업 목록 (T-17)"""
    filters = []
    if job_type is not None:
        filters.append(RegJob.type == job_type)
    if status is not None:
        filters.append(RegJob.status == status)

    total_count = session.scalar(select(func.count()).select_from(RegJob).where(*filters)) or 0
    rows = session.scalars(
        select(RegJob)
        .where(*filters)
        .order_by(RegJob.created_at.desc(), RegJob.job_id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    jobs = [
        {
            "job_id": job.job_id,
            "type": job.type,
            "status": job.status,
            "progress": job.progress,
            "created_at": to_kst_iso(job.created_at),
            "finished_at": to_kst_iso(job.finished_at),
        }
        for job in rows
    ]
    return ok({"jobs": jobs, "total_count": total_count})


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    """7.4.25 작업 상태 (T-17)"""
    job = session.get(RegJob, job_id)
    if job is None:
        raise TrainerError(Code.NOT_FOUND, f"job not found: {job_id}")
    return ok({
        "job_id": job.job_id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "hold_reason": job.hold_reason,
        "result": job.result,
        "fault_id": job.fault_id,
    })
