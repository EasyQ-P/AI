"""임베딩과 벡터 검색 (6.1.5). 담당: Codex 구현 → Claude 리뷰.

- Embedder: texts → 벡터 목록. task는 "query"(질문) 또는 "document"(교안 · 발화 조각).
- GeminiEmbedder: google-genai SDK(선택 설치 `retrieval[embedding]`), 키는 환경변수 GEMINI_API_KEY.
  SDK는 GeminiEmbedder를 만들 때만 import한다(학과 서버 Python 3.9에서는 설치하지 않는다).
- CachedEmbedder: 같은 (모델 · 차원 · task · 텍스트)는 다시 부르지 않도록 JSONL 파일에 캐시한다.
- FakeEmbedder: 시험 · CI용. 네트워크 없이 결정적인 벡터.
AI Hub 데이터는 절대 임베딩하지 않는다(해외 API). 걸러내는 책임은 호출하는 쪽(스크립트)에 있다.
"""

import hashlib
import json
import math
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

Task = Literal["query", "document"]
Vector = list[float]


class Embedder:
    """임베더 공통 형태. name · dim은 검색 설정(rc-vN)에 기록된다."""

    name: str = ""
    dim: int = 0

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        raise NotImplementedError


class FakeEmbedder(Embedder):
    """sha256 해시로 만든 결정적 단위 벡터. 같은 텍스트 → 같은 벡터, 다른 텍스트 → 거의 직교."""

    def __init__(self, dim: int = 64) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.name, self.dim = "fake", dim

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        vectors: list[Vector] = []
        for text in texts:
            raw = hashlib.shake_256(text.encode("utf-8")).digest(self.dim * 8)
            vector = [
                int.from_bytes(raw[offset:offset + 8], "big") / (2**63 - 0.5) - 1.0
                for offset in range(0, len(raw), 8)
            ]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


class GeminiEmbedder(Embedder):
    """gemini-embedding-2, output_dimensionality=dim. task → task_type(RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT).

    batch_size개씩 나눠 부르고, 429 · 5xx는 지수 백오프로 max_retries번 다시 시도한다.
    키가 없으면 RuntimeError. 키 값은 로그 · 예외 메시지에 넣지 않는다.
    """

    def __init__(self, model: str = "gemini-embedding-2", dim: int = 768,
                 batch_size: int = 100, max_retries: int = 5) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        try:
            api_key = os.environ["GEMINI_API_KEY"]
        except KeyError as exc:
            raise RuntimeError("GEMINI_API_KEY is required for GeminiEmbedder") from exc
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "GeminiEmbedder requires the 'embedding' extra: install retrieval[embedding]"
            ) from exc

        self.name = model
        self.dim = dim
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._types = types
        self._client = genai.Client(api_key=api_key)

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        vectors: list[Vector] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start:start + self.batch_size])
            for attempt in range(self.max_retries + 1):
                try:
                    response = self._client.models.embed_content(
                        model=self.name,
                        contents=batch,
                        config=self._types.EmbedContentConfig(
                            task_type=task_type,
                            output_dimensionality=self.dim,
                        ),
                    )
                    vectors.extend([list(embedding.values) for embedding in response.embeddings])
                    break
                except Exception as exc:
                    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                    response = getattr(exc, "response", None)
                    status_code = status_code or getattr(response, "status_code", None)
                    retryable = status_code == 429 or (
                        isinstance(status_code, int) and 500 <= status_code < 600
                    )
                    if not retryable or attempt >= self.max_retries:
                        raise
                    time.sleep(2**attempt)
        return vectors


class CachedEmbedder(Embedder):
    """inner 임베더 앞에 붙는 파일 캐시. 키 = sha256(f"{name}|{dim}|{task}|{text}"), 파일 한 줄 = {"key", "vec"}.

    캐시에 없는 텍스트만 inner로 한 번에 보내고, 결과를 파일 끝에 덧붙인다. 순서는 입력 순서 그대로.
    """

    def __init__(self, inner: Embedder, cache_path: Path) -> None:
        self.inner = inner
        self.name = inner.name
        self.dim = inner.dim
        self.cache_path = Path(cache_path)
        self._cache: dict[str, Vector] = {}
        if self.cache_path.exists():
            with self.cache_path.open("r", encoding="utf-8") as cache_file:
                for line in cache_file:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    self._cache[entry["key"]] = [float(value) for value in entry["vec"]]

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        keyed_texts = [(self._key(text, task), text) for text in texts]
        missing: dict[str, str] = {}
        for key, text in keyed_texts:
            if key not in self._cache:
                missing.setdefault(key, text)

        if missing:
            missing_keys = list(missing)
            vectors = self.inner.embed([missing[key] for key in missing_keys], task)
            if len(vectors) != len(missing_keys):
                raise ValueError("inner embedder returned a different number of vectors")
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as cache_file:
                for key, vector in zip(missing_keys, vectors):
                    stored = list(vector)
                    self._cache[key] = stored
                    cache_file.write(json.dumps({"key": key, "vec": stored}, ensure_ascii=False) + "\n")

        return [list(self._cache[key]) for key, _ in keyed_texts]

    def _key(self, text: str, task: Task) -> str:
        raw = f"{self.name}|{self.dim}|{task}|{text}".encode()
        return hashlib.sha256(raw).hexdigest()


def cosine_top_k(query: Vector, docs: dict[str, Vector], top_n: int = 20) -> list[tuple[str, float]]:
    """코사인 유사도 상위 top_n (id, 점수) 내림차순, 동점은 id 오름차순. numpy 없이 순수 파이썬."""
    if top_n <= 0:
        return []
    query_norm = math.sqrt(sum(value * value for value in query))
    results: list[tuple[str, float]] = []
    for doc_id, vector in docs.items():
        if len(vector) != len(query):
            raise ValueError("query and document vectors must have the same dimension")
        vector_norm = math.sqrt(sum(value * value for value in vector))
        denominator = query_norm * vector_norm
        similarity = sum(left * right for left, right in zip(query, vector)) / denominator if denominator else 0.0
        results.append((doc_id, similarity))
    results.sort(key=lambda item: (-item[1], item[0]))
    return results[:top_n]
