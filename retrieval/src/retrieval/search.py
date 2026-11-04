"""하이브리드 검색(R3) (6.1.5). 담당: 최의찬.

벡터 검색 20개 + 키워드(Kiwi + tsvector) 검색 20개를 RRF로 합쳐 상위 20개를 근거 후보로 쓴다.
항상 같은 강연 안에서만 검색한다.
"""

RRF_K = 60


def rrf_merge(vector_ids: list[str], keyword_ids: list[str], top_n: int = 20, k: int = RRF_K) -> list[str]:
    """두 순위 목록을 Reciprocal Rank Fusion으로 합친다."""
    scores: dict[str, float] = {}
    for ranked in (vector_ids, keyword_ids):
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda c: (-scores[c], c))[:top_n]


def tokenize_keywords(text: str) -> list[str]:
    """Kiwi 형태소 분석으로 키워드 색인용 토큰을 만든다 (영어 용어는 소문자 그대로)."""
    raise NotImplementedError
