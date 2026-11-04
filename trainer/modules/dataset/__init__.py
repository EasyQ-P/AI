"""데이터셋 관리모듈 (L1) — T-01~T-04, T-22. 담당: 엄윤종, 최의찬."""


def validate_dataset(source_dir: str):
    """데이터셋 폴더 검사 → ValidationReport(오류 행 · 통계). 실패 시 601 (T-01, 6.4.1)."""
    raise NotImplementedError


def build_eval_slide_chunks(dataset_version: str) -> str:
    """평가용 교안 조각 목록을 만들어 eval_slide_version(es-vN)을 돌려준다 (T-01, T-22)."""
    raise NotImplementedError


def mask_pii(text: str) -> tuple[str, int]:
    """질문 · 근거 문자열의 개인정보를 가리고 (가린 문자열, 가린 항목 수)를 돌려준다 (T-03)."""
    raise NotImplementedError


def merge_labels(base_version: str, items: list[dict], request_id: str) -> str:
    """검수 라벨을 학습셋에만 추가한 새 dataset_version을 만든다 (T-03).
    겹침 검사는 retrieval.check_overlap을 쓴다."""
    raise NotImplementedError
