"""학습서버 API 진입점 (7.4). 학과 서버 localhost:8000에서만 받고, EC2는 SSH 터널로 접근한다.

실행: uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.core.errors import TrainerError

app = FastAPI(title="EasyQ 학습서버", version="0.1.0", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
app.include_router(router, prefix="/api/v1")


@app.exception_handler(TrainerError)
async def trainer_error_handler(_: Request, exc: TrainerError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.body())
