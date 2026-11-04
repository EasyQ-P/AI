"""검색 설정 버전(retrieval_config_version, rc-vN).

청킹 규칙 · 임베딩 모델과 차원 · 형태소 분석기 버전 · 결합 방식 · 후보 수 · 코드 버전을 묶은 불변 버전이다.
학습 데이터 레지스트리와 서비스 판정 기록에 함께 남긴다 (6.1.5).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalConfig:
    version: str = "rc-v1"
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 768
    morph_analyzer: str = "kiwipiepy"
    fusion: str = "rrf"
    vector_top_k: int = 20
    keyword_top_k: int = 20
    candidates: int = 20
    utterance_chunk_seconds: int = 30


DEFAULT_CONFIG = RetrievalConfig()
