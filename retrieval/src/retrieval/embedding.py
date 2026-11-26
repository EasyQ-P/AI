"""임베딩과 벡터 검색 (6.1.5). 담당: Codex 구현 → Claude 리뷰.

- Embedder: texts → 벡터 목록. task는 "query"(질문) 또는 "document"(교안 · 발화 조각).
- GeminiEmbedder: google-genai SDK(선택 설치 `retrieval[embedding]`), 키는 환경변수 GEMINI_API_KEY.
  SDK는 GeminiEmbedder를 만들 때만 import한다(학과 서버 Python 3.9에서는 설치하지 않는다).
- CachedEmbedder: 같은 (모델 · 차원 · task · 텍스트)는 다시 부르지 않도록 JSONL 파일에 캐시한다.
- FakeEmbedder: 시험 · CI용. 네트워크 없이 결정적인 벡터.
AI Hub 데이터는 절대 임베딩하지 않는다(해외 API). 걸러내는 책임은 호출하는 쪽(스크립트)에 있다.
"""

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
        self.name, self.dim = "fake", dim

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        raise NotImplementedError


class GeminiEmbedder(Embedder):
    """gemini-embedding-2, output_dimensionality=dim. task → task_type(RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT).

    batch_size개씩 나눠 부르고, 429 · 5xx는 지수 백오프로 max_retries번 다시 시도한다.
    키가 없으면 RuntimeError. 키 값은 로그 · 예외 메시지에 넣지 않는다.
    """

    def __init__(self, model: str = "gemini-embedding-2", dim: int = 768,
                 batch_size: int = 100, max_retries: int = 5) -> None:
        raise NotImplementedError

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        raise NotImplementedError


class CachedEmbedder(Embedder):
    """inner 임베더 앞에 붙는 파일 캐시. 키 = sha256(f"{name}|{dim}|{task}|{text}"), 파일 한 줄 = {"key", "vec"}.

    캐시에 없는 텍스트만 inner로 한 번에 보내고, 결과를 파일 끝에 덧붙인다. 순서는 입력 순서 그대로.
    """

    def __init__(self, inner: Embedder, cache_path: Path) -> None:
        raise NotImplementedError

    def embed(self, texts: Sequence[str], task: Task) -> list[Vector]:
        raise NotImplementedError


def cosine_top_k(query: Vector, docs: dict[str, Vector], top_n: int = 20) -> list[tuple[str, float]]:
    """코사인 유사도 상위 top_n (id, 점수) 내림차순, 동점은 id 오름차순. numpy 없이 순수 파이썬."""
    raise NotImplementedError
