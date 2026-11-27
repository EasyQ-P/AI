"""7.4.1 서버 상태 확인 (T-19). worker 판정 어댑터가 10초마다 부른다."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ok
from app.db import get_session
from app.db.models import RegDeployment
from app.jobs.runner import get_runner
from modules.inference import serving_state

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict:
    deployment = session.scalars(
        select(RegDeployment).order_by(RegDeployment.deployment_seq.desc()).limit(1)
    ).first()
    if deployment is None:
        mode = "LLM_ONLY"
        serving_version = None
        threshold = None
    else:
        mode = deployment.mode
        serving_version = deployment.serving_version
        threshold = deployment.threshold

    loaded = serving_state().loaded
    return ok({
        # 임대 방식(design-changes 3번)에서는 강연이 없을 때 미적재가 정상이라 status에 반영하지 않는다.
        # 적재 여부는 model_loaded로만 알린다.
        "status": "ok",
        "mode": mode,
        "serving_version": serving_version,
        "threshold": threshold,
        "gpu_busy": get_runner().gpu_job(session) is not None,
        "model_loaded": loaded,  # 백엔드 v1.4 R2: 판정 모델이 GPU에 올라가 있는지(임대 방식, design-changes 3번)
    })
