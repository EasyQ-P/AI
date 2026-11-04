"""평가용 강의 판정 · 병합 전 겹침 검사에 쓰는 겹침 계산 (6.1.6, 6.4.3).

정규화(NFKC, 영문 소문자, 문장부호를 공백으로, 연속 공백 정리) 뒤 연속 5단어 묶음 집합을 만들고,
겹침 비율 = 공통 묶음 수 / 검사 대상(강연 교안 조각) 쪽 묶음 수.
5단어보다 짧은 조각은 정규화한 전체 문장이 같은지로 본다.
"""

import re
import unicodedata
from collections.abc import Iterable

NGRAM = 5
CHUNK_OVERLAP_THRESHOLD = 0.8   # 조각 하나가 평가용 조각과 80% 이상 겹치면 "겹친 조각"
LECTURE_CHUNK_RATIO = 0.3       # 겹친 조각이 강연 교안 조각의 30% 이상이면 평가용 강의

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def ngrams(text: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def overlap_ratio(target: str, reference_texts: Iterable[str]) -> float:
    """검사 대상 조각(target)이 평가용 텍스트들과 얼마나 겹치는지 0~1로 돌려준다."""
    refs = list(reference_texts)
    target_grams = ngrams(target)
    if not target_grams:
        norm = normalize(target)
        return 1.0 if norm and any(normalize(r) == norm for r in refs) else 0.0
    ref_grams: set[tuple[str, ...]] = set()
    for r in refs:
        ref_grams |= ngrams(r)
    return len(target_grams & ref_grams) / len(target_grams)


def is_eval_lecture(lecture_chunks: list[str], eval_chunks: list[str]) -> bool:
    """강연 교안 조각 중 80% 이상 겹치는 조각이 30% 이상이면 평가용 강의다 (6.1.6-4)."""
    if not lecture_chunks:
        return False
    hit = sum(1 for c in lecture_chunks if overlap_ratio(c, eval_chunks) >= CHUNK_OVERLAP_THRESHOLD)
    return hit / len(lecture_chunks) >= LECTURE_CHUNK_RATIO


def check_overlap(items: list[str], eval_texts: list[str]) -> tuple[list[int], list[int]]:
    """병합 전 겹침 검사 (7.4.29 check_overlap). 통과 · 제외 항목의 인덱스를 돌려준다."""
    passed, excluded = [], []
    for i, text in enumerate(items):
        (excluded if overlap_ratio(text, eval_texts) >= CHUNK_OVERLAP_THRESHOLD else passed).append(i)
    return passed, excluded
