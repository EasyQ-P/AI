"""학습서버 API 진입점 (7.4). 학과 서버 localhost:8000에서만 받고, EC2는 SSH 터널로 접근한다.

실행: uv run uvicorn app.main:app --app-dir trainer --host 127.0.0.1 --port 8000
판정 추론은 별도 프로세스(app.inference_main, 127.0.0.1:8001)가 맡는다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.core.config import check_settings, get_settings
from app.core.errors import register_error_handlers
from app.jobs import runner


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    check_settings(get_settings())
    runner.start()  # 남은 작업 정리 + 상태 파일 → reg_jobs 주기 동기화
    try:
        yield
    finally:
        runner.stop()  # 동기화만 멈춘다. 작업 프로세스는 그대로 돈다


app = FastAPI(
    title="EasyQ 학습서버",
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)
register_error_handlers(app)
app.include_router(router, prefix="/api/v1")
