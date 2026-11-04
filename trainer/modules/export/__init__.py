"""배포모듈 (L3) 변환 — T-11. 담당: 최의찬."""


def export_fp16(checkpoint: str) -> str:
    """fp32 체크포인트 → model.safetensors(fp16) 경로. 실패 시 604."""
    raise NotImplementedError


def measure_latency(model_path: str, n_pairs: int = 20) -> float:
    """질문 1개 + 근거 20개 추론 시간 p95(ms)."""
    raise NotImplementedError
