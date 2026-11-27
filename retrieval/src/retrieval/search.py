"""하이브리드 검색(R3) (6.1.5). 담당: 최의찬.

벡터 검색 20개 + 키워드(Kiwi) 검색 20개를 RRF로 합쳐 상위 20개를 근거 후보로 쓴다.
항상 같은 강연(강의) 안에서만 검색한다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig
from retrieval.embedding import Embedder, cosine_top_k
from retrieval.keyword import build_keyword_index, tokenize_keywords

RRF_K = DEFAULT_CONFIG.rrf_k


def rrf_merge(vector_ids: list[str], keyword_ids: list[str], top_n: int = 20, k: int = RRF_K) -> list[str]:
    """두 순위 목록을 Reciprocal Rank Fusion으로 합친다."""
    scores: dict[str, float] = {}
    for ranked in (vector_ids, keyword_ids):
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda c: (-scores[c], c))[:top_n]


@dataclass(frozen=True)
class SearchDoc:
    doc_id: str          # 근거 ID (발화 {lecture_id}_T0001, 교안 {lecture_id}_D3_1, 서비스는 chunk_id)
    text: str
    lecture_id: str      # 같은 강의(서비스는 강연) 안에서만 검색한다
    evidence_type: str   # TRANSCRIPT / DOCUMENT


class HybridSearcher:
    """조각 목록으로 키워드 · 벡터 색인을 만들고, 질문마다 같은 강의 안에서 후보를 뽑는다."""

    def __init__(self, docs: Sequence[SearchDoc], embedder: Embedder,
                 config: RetrievalConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.embedder = embedder
        self.docs: dict[str, SearchDoc] = {d.doc_id: d for d in docs}
        if len(self.docs) != len(docs):
            raise ValueError("duplicate doc_id")
        self._by_lecture: dict[str, set[str]] = {}
        for d in docs:
            self._by_lecture.setdefault(d.lecture_id, set()).add(d.doc_id)
        self.keyword = build_keyword_index({d.doc_id: d.text for d in docs}, config)
        ids = [d.doc_id for d in docs]
        vectors = embedder.embed([d.text for d in docs], "document") if docs else []
        if len(vectors) != len(ids):  # 개수가 다르면 zip이 조용히 잘라 검색 중 KeyError가 난다
            raise ValueError(f"embedder returned {len(vectors)} vectors for {len(ids)} docs")
        self.vectors = dict(zip(ids, vectors))

    def search_many(self, queries: Sequence[tuple[str, str]], top_n: Optional[int] = None) -> list[list[str]]:
        """(질문, lecture_id) 목록 → 질문마다 후보 근거 ID(RRF 순위). 질문 임베딩은 한 번에 부른다."""
        cfg = self.config
        n = cfg.candidates if top_n is None else top_n
        if n < 0:
            raise ValueError("top_n must be >= 0")
        qvecs = self.embedder.embed([q for q, _ in queries], "query") if queries else []
        if len(qvecs) != len(queries):  # 개수가 다르면 마지막 질문의 결과가 조용히 빠진다
            raise ValueError(f"embedder returned {len(qvecs)} vectors for {len(queries)} queries")
        results: list[list[str]] = []
        for (question, lecture_id), qvec in zip(queries, qvecs):
            allowed = self._by_lecture.get(lecture_id, set())
            if not allowed:
                results.append([])
                continue
            vec_ids = [i for i, _ in cosine_top_k(qvec, {i: self.vectors[i] for i in allowed}, cfg.vector_top_k)]
            kw_ids = [i for i, _ in self.keyword.search(tokenize_keywords(question, cfg), cfg.keyword_top_k,
                                                        allowed_ids=allowed)]
            results.append(rrf_merge(vec_ids, kw_ids, n, cfg.rrf_k))
        return results

    def search(self, question: str, lecture_id: str, top_n: Optional[int] = None) -> list[str]:
        return self.search_many([(question, lecture_id)], top_n)[0]
