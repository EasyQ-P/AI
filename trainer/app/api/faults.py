"""7.4.27 장애 기록 조회 (T-21)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ok
from app.core.timefmt import to_kst_iso
from app.db import get_session
from app.db.models import RegFault

router = APIRouter(tags=["faults"])


@router.get("/faults")
def list_faults(
    session: Annotated[Session, Depends(get_session)],
    from_: Annotated[Optional[AwareDatetime], Query(alias="from")] = None,
    to: Optional[AwareDatetime] = None,
    code: Optional[int] = None,
    job_id: Optional[str] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """7.4.27 장애 기록 조회 (T-21)"""
    filters = []
    if from_ is not None:
        filters.append(RegFault.occurred_at >= from_)
    if to is not None:
        filters.append(RegFault.occurred_at <= to)
    if code is not None:
        filters.append(RegFault.code == code)
    if job_id is not None:
        filters.append(RegFault.job_id == job_id)

    total_count = session.scalar(select(func.count()).select_from(RegFault).where(*filters)) or 0
    rows = session.scalars(
        select(RegFault)
        .where(*filters)
        .order_by(RegFault.occurred_at.desc(), RegFault.fault_id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    faults = [
        {
            "fault_id": fault.fault_id,
            "occurred_at": to_kst_iso(fault.occurred_at),
            "code": fault.code,
            "module": fault.module,
            "job_id": fault.job_id,
            "message": fault.message,
        }
        for fault in rows
    ]
    return ok({"faults": faults, "total_count": total_count})
