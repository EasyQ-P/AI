"""학습서버 오류 코드 (8.4). 응답은 공통 형식 {result_code, result_msg, data}."""

from enum import IntEnum


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
