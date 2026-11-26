"""검색 설정 버전(retrieval_config_version, rc-vN).

청킹 규칙 · 임베딩 모델과 차원 · 형태소 분석기 버전 · 결합 방식 · 후보 수 · 코드 버전을 묶은 불변 버전이다.
학습 데이터 레지스트리와 서비스 판정 기록에 함께 남긴다 (6.1.5). 값 하나라도 바꾸면 버전을 올린다.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RetrievalConfig:
    version: str = "rc-v1"
    # 교안 청킹 (백엔드 합의안, 엄윤종 slides-v4 / es-draft-3와 같은 값)
    tokenizer: str = "BAAI/bge-reranker-v2-m3"
    slide_max_tokens: int = 400
    slide_overlap_tokens: int = 50
    slide_min_chars: int = 20
    slide_min_content_words: int = 3        # Kiwi NNG · NNP + 영단어 [A-Za-z][A-Za-z0-9]+
    slide_min_word_char_ratio: float = 0.5
    slide_min_wordlike_token_ratio: float = 0.5
    # 발화 청킹
    utterance_chunk_seconds: int = 30
    # 임베딩
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 768
    # 키워드 검색 (Kiwi 형태소 → BM25)
    morph_analyzer: str = "kiwipiepy"
    keyword_tags: tuple[str, ...] = ("NNG", "NNP", "NR", "VV", "VA", "XR", "SL", "SH", "SN")
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    # 결합
    fusion: str = "rrf"
    rrf_k: int = 60
    vector_top_k: int = 20
    keyword_top_k: int = 20
    candidates: int = 20

    def to_dict(self) -> dict:
        """레지스트리 · 데이터셋 meta에 그대로 기록할 값."""
        return asdict(self)


DEFAULT_CONFIG = RetrievalConfig()
