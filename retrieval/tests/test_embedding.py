import builtins
import math

import pytest

from retrieval.embedding import CachedEmbedder, Embedder, FakeEmbedder, GeminiEmbedder, Task, cosine_top_k


class RecordingEmbedder(Embedder):
    name = "recording"
    dim = 2

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Task]] = []

    def embed(self, texts, task):
        self.calls.append((list(texts), task))
        return [[float(len(text)), float(index + 1)] for index, text in enumerate(texts)]


def test_fake_embedder_is_deterministic_and_unit_length() -> None:
    embedder = FakeEmbedder(dim=16)

    first = embedder.embed(["alpha", "beta"], "query")
    second = embedder.embed(["alpha", "beta"], "document")

    assert first == second
    assert first[0] != first[1]
    assert all(len(vector) == 16 for vector in first)
    assert all(math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0) for vector in first)


def test_cached_embedder_reuses_file_cache_and_preserves_order(tmp_path) -> None:
    cache_path = tmp_path / "vectors.jsonl"
    first_inner = RecordingEmbedder()
    first = CachedEmbedder(first_inner, cache_path)

    vectors = first.embed(["longer", "x", "longer"], "document")

    assert first_inner.calls == [(["longer", "x"], "document")]
    assert vectors == [[6.0, 1.0], [1.0, 2.0], [6.0, 1.0]]

    second_inner = RecordingEmbedder()
    second = CachedEmbedder(second_inner, cache_path)
    assert second.embed(["x", "longer"], "document") == [[1.0, 2.0], [6.0, 1.0]]
    assert second_inner.calls == []


def test_cached_embedder_only_requests_missing_texts(tmp_path) -> None:
    cache_path = tmp_path / "vectors.jsonl"
    initial_inner = RecordingEmbedder()
    CachedEmbedder(initial_inner, cache_path).embed(["cached"], "query")

    inner = RecordingEmbedder()
    embedder = CachedEmbedder(inner, cache_path)

    vectors = embedder.embed(["cached", "new", "cached"], "query")

    assert inner.calls == [(["new"], "query")]
    assert vectors == [[6.0, 1.0], [3.0, 1.0], [6.0, 1.0]]


def test_cache_key_separates_tasks(tmp_path) -> None:
    inner = RecordingEmbedder()
    embedder = CachedEmbedder(inner, tmp_path / "vectors.jsonl")

    embedder.embed(["same"], "query")
    embedder.embed(["same"], "document")

    assert inner.calls == [(["same"], "query"), (["same"], "document")]


def test_cosine_top_k_sorts_by_score_then_id() -> None:
    docs = {
        "orthogonal": [0.0, 1.0],
        "same-b": [2.0, 0.0],
        "same-a": [1.0, 0.0],
        "opposite": [-1.0, 0.0],
    }

    results = cosine_top_k([1.0, 0.0], docs, top_n=3)

    assert [doc_id for doc_id, _ in results] == ["same-a", "same-b", "orthogonal"]
    assert [score for _, score in results] == pytest.approx([1.0, 1.0, 0.0])


def test_cosine_top_k_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="same dimension"):
        cosine_top_k([1.0], {"bad": [1.0, 0.0]})


def test_gemini_embedder_requires_key_without_exposing_value(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiEmbedder()


def test_gemini_embedder_has_friendly_missing_sdk_error(monkeypatch) -> None:
    secret = "test-secret-value"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    original_import = builtins.__import__

    def reject_google(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google" or name.startswith("google."):
            raise ImportError("missing google SDK")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_google)

    with pytest.raises(RuntimeError, match="embedding") as error:
        GeminiEmbedder()
    assert secret not in str(error.value)


class _FakeModels:
    def __init__(self, merge: bool) -> None:
        self.merge = merge
        self.calls = 0

    def embed_content(self, model, contents, config):
        from types import SimpleNamespace

        self.calls += 1
        count = 1 if self.merge else len(contents)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(i), 1.0]) for i in range(count)])


def _fake_gemini(merge: bool, batch_size: int = 2) -> GeminiEmbedder:
    from types import SimpleNamespace

    embedder = GeminiEmbedder.__new__(GeminiEmbedder)
    embedder.name, embedder.dim, embedder.batch_size, embedder.max_retries = "gemini-embedding-2", 2, batch_size, 0
    embedder._types = SimpleNamespace(
        Content=lambda parts: SimpleNamespace(parts=parts),
        Part=lambda text: SimpleNamespace(text=text),
        EmbedContentConfig=lambda **kwargs: kwargs,
    )
    embedder._client = SimpleNamespace(models=_FakeModels(merge))
    return embedder


def test_gemini_returns_one_vector_per_text_across_batches() -> None:
    embedder = _fake_gemini(merge=False, batch_size=2)

    vectors = embedder.embed(["a", "b", "c"], "document")

    assert len(vectors) == 3
    assert embedder._client.models.calls == 2


def test_gemini_count_mismatch_raises() -> None:
    embedder = _fake_gemini(merge=True)

    with pytest.raises(RuntimeError, match="1 embeddings for 2 texts"):
        embedder.embed(["a", "b"], "query")
