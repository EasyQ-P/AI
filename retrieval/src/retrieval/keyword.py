"""형태소 분석 키워드 검색 (Kiwi + BM25) (6.1.5). 담당: Codex 구현 → Claude 리뷰.

서비스에서는 같은 토큰을 DB 키워드 색인에 넣고, 데이터셋 구축 · 시험에서는 메모리 BM25로 검색한다.
kiwipiepy는 선택 설치(`retrieval[keyword]`). 모듈을 import만 할 때는 kiwipiepy가 없어도 된다.
"""

from collections.abc import Mapping, Sequence
from typing import Optional

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig


def tokenize_keywords(text: str, config: RetrievalConfig = DEFAULT_CONFIG) -> list[str]:
    """Kiwi로 형태소를 나눠 config.keyword_tags 품사만 남긴 키워드 토큰 목록.

    - 동사 · 형용사(VV · VA)는 어간 형태 그대로(예: "계산하"), 나머지는 형태 그대로.
    - 영어(SL)는 소문자로. 한 글자 한글 명사는 남기고, 빈 문자열은 버린다.
    - 같은 토큰이 여러 번 나오면 여러 번 넣는다(BM25 tf 계산용).
    - Kiwi 객체는 모듈 안에서 한 번만 만든다(지연 생성).
    """
    raise NotImplementedError


class BM25Index:
    """문서 id → 토큰 목록으로 만든 메모리 BM25 색인 (Okapi BM25, idf = ln(1 + (N - df + 0.5) / (df + 0.5)))."""

    def __init__(self, docs: Mapping[str, Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        raise NotImplementedError

    def search(self, query_tokens: Sequence[str], top_n: int = 20,
               allowed_ids: Optional[set] = None) -> list[tuple[str, float]]:
        """점수가 0보다 큰 문서만 (id, 점수) 내림차순. 동점은 id 오름차순. allowed_ids가 있으면 그 안에서만."""
        raise NotImplementedError


def build_keyword_index(texts: dict[str, str], config: RetrievalConfig = DEFAULT_CONFIG) -> BM25Index:
    """id → 원문을 tokenize_keywords로 나눠 BM25Index를 만든다."""
    return BM25Index({i: tokenize_keywords(t, config) for i, t in texts.items()}, config.bm25_k1, config.bm25_b)
