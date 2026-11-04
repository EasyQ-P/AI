"""판정 추론 프로세스 진입점 (2.3, 6.4.11, 6.4.14). 학습 · 평가 · 변환과 분리해 따로 띄운다.

서빙 버전의 fp16 모델을 GPU에 상주시키고, 학습이 도는 중에도 판정에 응답한다.
127.0.0.1:8001 내부 전용이며 외부 · 터널에는 열지 않는다. API 서버(8000)의 7.4.26이 이쪽을 부른다.

실행: uv run uvicorn app.inference_main:app --app-dir trainer --host 127.0.0.1 --port 8001
"""

from fastapi import FastAPI

from app.core.errors import ok, register_error_handlers
from modules.inference import serving_state

app = FastAPI(title="EasyQ 판정 추론", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
register_error_handlers(app)


@app.get("/internal/health")
async def internal_health() -> dict:
    """API 서버(7.4.1)가 서빙 상태를 확인할 때 쓴다."""
    s = serving_state()
    return ok({"mode": s.mode, "serving_version": s.serving_version, "threshold": s.threshold, "loaded": s.loaded})


# TODO 내부 경로 (구현 전)
# POST /internal/score  질문 + 후보 최대 20개 → 근거별 점수 (modules.inference.score)
# POST /internal/load   새 버전 나란히 적재 → 시험 질문 5건 점검 → 교체 (modules.inference.load_model)
