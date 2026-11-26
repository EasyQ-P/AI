"""학습모듈 (L2) — T-05~T-08. 담당: 최의찬."""

from typing import Optional


def build_pairs(dataset, hard_negatives: int):
    """(질문, 근거, 0/1) 쌍과 pos_weight를 만든다 (T-05)."""
    raise NotImplementedError


def train(config: dict, dataset_version: str, init_from: Optional[str] = None):
    """bge-reranker-v2-m3 파인튜닝(fp16 혼합 정밀도) → CheckpointInfo(경로 · best_epoch · curve · seed)."""
    raise NotImplementedError
