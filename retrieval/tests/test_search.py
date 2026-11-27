import pytest

from retrieval.embedding import FakeEmbedder
from retrieval.search import HybridSearcher, SearchDoc

pytest.importorskip("kiwipiepy")  # 키워드 색인(Kiwi)

DOCS = [SearchDoc(f"L1_D{i}_1", f"binary search tree node {i}", "L1", "DOCUMENT") for i in range(1, 4)]


class ShortEmbedder(FakeEmbedder):
    """마지막 벡터 하나를 빠뜨리는 잘못된 임베더."""

    def embed(self, texts, task):
        return super().embed(texts, task)[:-1]


def test_top_n_zero_means_zero_and_negative_is_rejected():
    searcher = HybridSearcher(DOCS, FakeEmbedder())
    assert searcher.search("binary search", "L1", top_n=0) == []
    assert len(searcher.search("binary search", "L1")) == 3  # None이면 기본값(20)까지
    with pytest.raises(ValueError):
        searcher.search("binary search", "L1", top_n=-1)


def test_embedder_count_mismatch_fails_fast():
    with pytest.raises(ValueError, match="vectors for 3 docs"):
        HybridSearcher(DOCS, ShortEmbedder())

    searcher = HybridSearcher(DOCS, FakeEmbedder())
    searcher.embedder = ShortEmbedder()
    with pytest.raises(ValueError, match="vectors for 2 queries"):
        searcher.search_many([("a", "L1"), ("b", "L1")])
