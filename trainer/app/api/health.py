"""7.4.1 서버 상태 확인 (T-19). worker 판정 어댑터가 10초마다 부른다."""

from fastapi import APIRouter

from app.core.errors import ok
from modules.inference import serving_state

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    s = serving_state()
    return ok({
        "status": "ok" if s.loaded or s.mode == "LLM_ONLY" else "degraded",
        "mode": s.mode,
        "serving_version": s.serving_version,
        "threshold": s.threshold,
        "gpu_busy": s.gpu_busy,
    })
