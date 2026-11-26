"""교안 청킹(R1) · 확정 발화 30초 청킹(R2) (6.1.5). 담당: 조현준(교안), 최의찬(발화)."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Chunk:
    text: str
    page_no: Optional[int] = None      # 교안 조각
    start_ms: Optional[int] = None     # 발화 조각
    end_ms: Optional[int] = None


def chunk_slides(pages: list[str]) -> list[Chunk]:
    """교안 페이지 텍스트를 검색 조각으로 나눈다."""
    raise NotImplementedError


def chunk_utterances(segments: list[tuple[int, int, str]], seconds: int = 30) -> list[Chunk]:
    """확정 발화 (start_ms, end_ms, text) 목록을 30초 단위 조각으로 묶는다."""
    raise NotImplementedError
