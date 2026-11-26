"""형태소 분석 키워드 검색 (Kiwi + BM25) (6.1.5). 담당: Codex 구현 → Claude 리뷰.

서비스에서는 같은 토큰을 DB 키워드 색인에 넣고, 데이터셋 구축 · 시험에서는 메모리 BM25로 검색한다.
kiwipiepy는 선택 설치(`retrieval[keyword]`). 모듈을 import만 할 때는 kiwipiepy가 없어도 된다.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Optional

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig

_KIWI = None


def tokenize_keywords(text: str, config: RetrievalConfig = DEFAULT_CONFIG) -> list[str]:
    """Kiwi로 형태소를 나눠 config.keyword_tags 품사만 남긴 키워드 토큰 목록.

    - 동사 · 형용사(VV · VA)는 어간 형태 그대로(예: "계산하"), 나머지는 형태 그대로.
    - 영어(SL)는 소문자로. 한 글자 한글 명사는 남기고, 빈 문자열은 버린다.
    - 같은 토큰이 여러 번 나오면 여러 번 넣는다(BM25 tf 계산용).
    - Kiwi 객체는 모듈 안에서 한 번만 만든다(지연 생성).
    """
    global _KIWI
    if _KIWI is None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as exc:
            raise RuntimeError(
                "tokenize_keywords requires the 'keyword' extra: "
                "install retrieval[keyword]"
            ) from exc
        _KIWI = Kiwi()

    allowed_tags = set(config.keyword_tags)
    keywords: list[str] = []
    for token in _KIWI.tokenize(text):
        tag = token.tag.split("-", 1)[0]
        if tag not in allowed_tags:
            continue
        form = token.form.strip()
        if not form:
            continue
        keywords.append(form.lower() if tag == "SL" else form)
    return keywords


class BM25Index:
    """문서 id → 토큰 목록으로 만든 메모리 BM25 색인 (Okapi BM25, idf = ln(1 + (N - df + 0.5) / (df + 0.5)))."""

    def __init__(self, docs: Mapping[str, Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._term_frequencies = {doc_id: Counter(tokens) for doc_id, tokens in docs.items()}
        self._lengths = {doc_id: sum(frequencies.values()) for doc_id, frequencies in self._term_frequencies.items()}
        self._document_count = len(self._term_frequencies)
        self._average_length = (
            sum(self._lengths.values()) / self._document_count if self._document_count else 0.0
        )

        document_frequencies: Counter = Counter()
        for frequencies in self._term_frequencies.values():
            document_frequencies.update(frequencies.keys())
        self._idf = {
            token: math.log(1.0 + (self._document_count - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequencies.items()
        }

    def search(self, query_tokens: Sequence[str], top_n: int = 20,
               allowed_ids: Optional[set] = None) -> list[tuple[str, float]]:
        """점수가 0보다 큰 문서만 (id, 점수) 내림차순. 동점은 id 오름차순. allowed_ids가 있으면 그 안에서만."""
        if top_n <= 0 or not query_tokens or not self._document_count:
            return []

        scores: list[tuple[str, float]] = []
        for doc_id, frequencies in self._term_frequencies.items():
            if allowed_ids is not None and doc_id not in allowed_ids:
                continue
            score = 0.0
            length = self._lengths[doc_id]
            length_ratio = length / self._average_length if self._average_length else 0.0
            for token in query_tokens:
                term_frequency = frequencies.get(token, 0)
                if not term_frequency:
                    continue
                denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)
                score += self._idf[token] * term_frequency * (self.k1 + 1.0) / denominator
            if score > 0.0:
                scores.append((doc_id, score))

        scores.sort(key=lambda item: (-item[1], item[0]))
        return scores[:top_n]


def build_keyword_index(texts: dict[str, str], config: RetrievalConfig = DEFAULT_CONFIG) -> BM25Index:
    """id → 원문을 tokenize_keywords로 나눠 BM25Index를 만든다."""
    return BM25Index({i: tokenize_keywords(t, config) for i, t in texts.items()}, config.bm25_k1, config.bm25_b)
