import math

import pytest

from retrieval.config import DEFAULT_CONFIG
from retrieval.keyword import BM25Index, tokenize_keywords


def test_bm25_ranks_scores_and_excludes_zero_scores() -> None:
    index = BM25Index(
        {
            "short": ["apple"],
            "repeated": ["apple", "apple"],
            "unmatched": ["banana"],
        },
        k1=1.5,
        b=0.75,
    )

    results = index.search(["apple"], top_n=10)

    assert [doc_id for doc_id, _ in results] == ["repeated", "short"]
    assert all(score > 0.0 for _, score in results)
    assert "unmatched" not in {doc_id for doc_id, _ in results}


def test_bm25_uses_document_frequency_formula() -> None:
    index = BM25Index({"a": ["term"], "b": ["other"]}, k1=1.5, b=0.75)

    results = index.search(["term"])

    expected_idf = math.log(1.0 + (2 - 1 + 0.5) / (1 + 0.5))
    assert results == [("a", pytest.approx(expected_idf))]


def test_bm25_breaks_ties_by_id_and_honors_allowed_ids() -> None:
    index = BM25Index({"b": ["same"], "a": ["same"], "c": ["same"]})

    assert [doc_id for doc_id, _ in index.search(["same"], top_n=2)] == ["a", "b"]
    assert [doc_id for doc_id, _ in index.search(["same"], allowed_ids={"b", "c"})] == ["b", "c"]
    assert index.search(["missing"]) == []
    assert index.search(["same"], top_n=0) == []


def test_tokenize_keywords_handles_korean_and_english() -> None:
    pytest.importorskip("kiwipiepy")

    tokens = tokenize_keywords("AI 모델이 빠르게 계산한다.", DEFAULT_CONFIG)

    assert "ai" in tokens
    assert "모델" in tokens
    assert "빠르" in tokens
    assert "계산" in tokens or "계산하" in tokens
    assert all(token == token.lower() for token in tokens if token.isascii())


def test_tokenize_keywords_keeps_repeated_terms() -> None:
    pytest.importorskip("kiwipiepy")

    tokens = tokenize_keywords("질문 질문에 답한다.")

    assert tokens.count("질문") == 2
