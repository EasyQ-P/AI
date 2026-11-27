"""학습서버 오류 코드 (8.4). 응답은 공통 형식 {result_code, result_msg, data}."""

import logging
from enum import IntEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class Code(IntEnum):
    INTERNAL = 600                # 정의되지 않은 오류
    DATASET_INVALID = 601         # 데이터셋 검증 오류
    COLLECTION_FAILED = 602       # 데이터 수집 오류
    PARAM_OUT_OF_RANGE = 603      # 학습 파라미터 허용 범위 밖
    EXPORT_FAILED = 604           # fp16 변환 오류
    DEPLOY_FAILED = 605           # 서빙 전환 오류(적재 · 점검 실패)
    TRAIN_FAILED = 606            # 학습 실패
    EVAL_FAILED = 607             # 평가 오류
    NOT_CANCELLABLE = 608         # 중단할 수 없는 작업
    GPU_BUSY = 609                # GPU 사용 중
    MODEL_STATE = 610             # 모델 버전 상태 오류
    INFERENCE_FAILED = 611        # 판정 추론 오류 · LLM_ONLY 모드
    API_KEY = 612                 # API 키 인증 오류
    NOT_FOUND = 613               # 없는 데이터셋 · 모델 · 작업 · 평가
    DEPLOY_CRITERIA = 614         # 배포 기준 미달
    REGISTER_HELD = 615           # 등록 조건 미달


HTTP_STATUS = {
    Code.DATASET_INVALID: 400, Code.PARAM_OUT_OF_RANGE: 400, Code.API_KEY: 401, Code.NOT_FOUND: 404,
    Code.NOT_CANCELLABLE: 409, Code.GPU_BUSY: 409, Code.MODEL_STATE: 409, Code.DEPLOY_CRITERIA: 409,
    Code.REGISTER_HELD: 409,
}

# 요청 형식 오류(422)를 어떤 코드로 돌려줄지 (8.4.3, design-changes 6번)
# 601(데이터셋 검증 오류 → 서비스 DATASET_NOT_READY)은 데이터셋 등록 · 라벨 병합 본문에만 쓴다.
# 그 밖의 입력 오류(조회 조건 · 쪽 번호 · 학습 파라미터 등)는 603(→ 서비스 VALIDATION_ERROR).
DATASET_BODY_PREFIX = "/api/v1/datasets"


class TrainerError(Exception):
    def __init__(self, code: Code, msg: str = "", data: object = None):
        super().__init__(msg)
        self.code, self.msg, self.data = code, msg, data

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def body(self) -> dict:
        return {"result_code": int(self.code), "result_msg": self.msg, "data": self.data}


def ok(data: object = None, msg: str = "") -> dict:
    return {"result_code": 200, "result_msg": msg, "data": data}


def not_implemented(api: str) -> TrainerError:
    """뼈대만 있는 API용. 구현 전까지 600으로 응답한다."""
    return TrainerError(Code.INTERNAL, f"not implemented: {api}")


def _body(code: Code, msg: str, data: object = None) -> dict:
    return {"result_code": int(code), "result_msg": msg, "data": data}


def validation_code(method: str, path: str) -> Code:
    if method == "POST" and path.startswith(DATASET_BODY_PREFIX):
        return Code.DATASET_INVALID
    return Code.PARAM_OUT_OF_RANGE


def register_error_handlers(app: FastAPI) -> None:
    """모든 오류를 공통 응답 형식으로 바꾼다."""

    @app.exception_handler(TrainerError)
    async def trainer_error(_: Request, exc: TrainerError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 입력값(input)은 원문이 섞일 수 있어 돌려주지 않고 위치 · 사유만 남긴다
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
        code = validation_code(request.method, request.url.path)
        return JSONResponse(status_code=400, content=_body(code, "invalid request", errors))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: Code.API_KEY, 404: Code.NOT_FOUND}.get(exc.status_code, Code.INTERNAL)
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content=_body(Code.INTERNAL, "internal error"))
