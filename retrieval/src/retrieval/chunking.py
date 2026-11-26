"""교안 청킹(R1) · 확정 발화 30초 청킹(R2) (6.1.5).

교안: Claude 구현(slides-v4 규칙). 발화: Codex 구현 → Claude 리뷰.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable, Optional

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig

# 텍스트 → 토큰마다 (시작, 끝) 문자 위치. 서비스 · 데이터셋 모두 bge 토크나이저로 센다(bge_token_spans).
TokenSpans = Callable[[str], list[tuple[int, int]]]


@dataclass(frozen=True)
class Chunk:
    text: str
    page_no: Optional[int] = None    # 교안 조각: 쪽 번호(1부터)
    part: Optional[int] = None       # 교안 조각: 그 쪽 안의 순번(1부터). 근거 ID = {lecture_id}_D{page_no}_{part}
    start_ms: Optional[int] = None   # 발화 조각
    end_ms: Optional[int] = None
    token_count: Optional[int] = None


def bge_token_spans(tokenizer_name: str = DEFAULT_CONFIG.tokenizer) -> TokenSpans:
    """Hugging Face tokenizers로 특수 토큰을 뺀 토큰 위치를 돌려주는 함수를 만든다(선택 설치 `retrieval[tokenizer]`)."""
    raise NotImplementedError


def chunk_slides(pages: Sequence[str], token_spans: TokenSpans,
                 config: RetrievalConfig = DEFAULT_CONFIG) -> list[Chunk]:
    """교안 쪽별 텍스트 → 교안 조각 (slides-v4 규칙, 1쪽 = 1조각, 길면 겹쳐 나눔, 내용 적은 쪽 제외)."""
    raise NotImplementedError


def chunk_utterances(segments: Sequence[tuple[int, int, str]],
                     seconds: int = DEFAULT_CONFIG.utterance_chunk_seconds) -> list[Chunk]:
    """확정 발화 (start_ms, end_ms, text) 목록을 30초 단위 조각으로 묶는다. 담당: Codex.

    - start_ms 순으로 정렬해서 본다. 조각의 시작 = 첫 발화의 start_ms.
    - 다음 발화의 start_ms가 (조각 시작 + seconds*1000) 이상이면 새 조각을 연다. 발화 하나는 쪼개지 않는다.
    - text = 발화 text를 strip해서 공백 하나로 이은 것. 빈 발화는 건너뛴다. end_ms = 조각 마지막 발화의 end_ms.
    """
    raise NotImplementedError
