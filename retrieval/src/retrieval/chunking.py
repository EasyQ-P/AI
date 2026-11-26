"""교안 청킹(R1) · 확정 발화 30초 청킹(R2) (6.1.5). 담당: 최의찬(Claude).

교안 규칙(slides-v4, 백엔드 합의안 · rc-v1):
1. 쪽마다 줄 단위로 정리한다. 깨진 줄(글자 비율 · 낱말 비율이 기준 미만)은 뺀다.
2. 남은 글자가 slide_min_chars 미만이거나, 내용어(한국어 명사 NNG · NNP + 영단어)가
   slide_min_content_words 미만인 쪽은 조각을 만들지 않는다.
3. 1쪽 = 1조각. slide_max_tokens를 넘으면 slide_overlap_tokens만큼 겹치게 나눈다. 쪽을 넘겨 붙이지 않는다.
출처별 처리(저작권 문구 · 제3자 저작물 제거, 파일 읽기)는 호출하는 쪽(worker · 데이터 스크립트)이 한다.
엄윤종 slides-v4 코드와 결과 비교 전이다(PROGRESS.md 단계 7).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig

# 텍스트 → 토큰마다 (시작, 끝) 문자 위치. 서비스 · 데이터셋 모두 bge 토크나이저로 센다(bge_token_spans).
TokenSpans = Callable[[str], list[tuple[int, int]]]

_GARBLED_IGNORED = set("\"'(),:=[]{}")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class Chunk:
    text: str
    page_no: Optional[int] = None    # 교안 조각: 쪽 번호(1부터)
    part: Optional[int] = None       # 교안 조각: 그 쪽 안의 순번(1부터). 근거 ID = {lecture_id}_D{page_no}_{part}
    start_ms: Optional[int] = None   # 발화 조각
    end_ms: Optional[int] = None
    token_count: Optional[int] = None


def bge_token_spans(tokenizer_name: str = DEFAULT_CONFIG.tokenizer) -> TokenSpans:
    """Hugging Face tokenizers로 특수 토큰을 뺀 토큰 위치를 돌려주는 함수를 만든다(선택 설치 `retrieval[tokenizer]`).

    처음 부를 때 Hugging Face에서 tokenizer.json을 받는다. 로컬 경로(파일)를 주면 그 파일을 쓴다.
    """
    tokenizer = _load_tokenizer(tokenizer_name)

    def spans(text: str) -> list[tuple[int, int]]:
        return [tuple(o) for o in tokenizer.encode(text, add_special_tokens=False).offsets]

    return spans


@lru_cache(maxsize=4)
def _load_tokenizer(name: str):
    try:
        from tokenizers import Tokenizer
    except ImportError as e:  # pragma: no cover - 선택 설치
        raise ImportError("tokenizers가 필요합니다: retrieval[tokenizer]") from e
    if name.endswith(".json"):
        return Tokenizer.from_file(name)
    return Tokenizer.from_pretrained(name)


def _is_wordlike(token: str) -> bool:
    chars = [c for c in token if c not in _GARBLED_IGNORED]
    return bool(chars) and sum(c.isalnum() for c in chars) / len(chars) >= 0.5


def _is_garbled(line: str, config: RetrievalConfig) -> bool:
    """PDF 글자 깨짐 줄: 글자(문자 · 숫자) 비율 또는 낱말처럼 보이는 토큰 비율이 기준 미만."""
    chars = [c for c in line if not c.isspace() and c not in _GARBLED_IGNORED]
    if not chars:
        return False  # 괄호 · 따옴표만 있는 줄은 깨짐으로 보지 않는다(내용 기준에서 걸러진다)
    if sum(c.isalnum() for c in chars) / len(chars) < config.slide_min_word_char_ratio:
        return True
    tokens = line.split()
    return sum(_is_wordlike(t) for t in tokens) / len(tokens) < config.slide_min_wordlike_token_ratio


def clean_page(text: str, config: RetrievalConfig = DEFAULT_CONFIG) -> str:
    """줄 끝 공백 · 빈 줄 · 깨진 줄을 빼고 줄바꿈으로 다시 잇는다."""
    lines = (ln.strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln and not _is_garbled(ln, config))


def count_content_words(text: str) -> int:
    """내용어 수 = 영단어([A-Za-z][A-Za-z0-9]+) + 한국어 일반 · 고유명사(Kiwi NNG · NNP).

    한글이 있으면 kiwipiepy가 필요하다(`retrieval[keyword]`). 한글이 없으면 Kiwi 없이 센다.
    """
    n = len(_LATIN_WORD.findall(text))
    if _HANGUL.search(text):
        n += sum(1 for t in _kiwi().tokenize(text) if t.tag in ("NNG", "NNP"))
    return n


@lru_cache(maxsize=1)
def _kiwi():
    try:
        from kiwipiepy import Kiwi
    except ImportError as e:  # pragma: no cover - 선택 설치
        raise ImportError("한글 교안 청킹에는 kiwipiepy가 필요합니다: retrieval[keyword]") from e
    return Kiwi()


def chunk_slides(pages: Sequence[str], token_spans: TokenSpans,
                 config: RetrievalConfig = DEFAULT_CONFIG) -> list[Chunk]:
    """교안 쪽별 텍스트(pages[0] = 1쪽) → 교안 조각. 빠진 쪽은 조각이 없을 뿐 쪽 번호는 원래대로 남는다."""
    if config.slide_overlap_tokens >= config.slide_max_tokens:
        raise ValueError("slide_overlap_tokens must be smaller than slide_max_tokens")
    chunks: list[Chunk] = []
    for page_no, raw in enumerate(pages, start=1):
        text = clean_page(raw, config)
        if len(text) < config.slide_min_chars or count_content_words(text) < config.slide_min_content_words:
            continue
        spans = token_spans(text)
        if len(spans) <= config.slide_max_tokens:
            chunks.append(Chunk(text=text, page_no=page_no, part=1, token_count=len(spans)))
            continue
        start, part = 0, 1
        while True:
            end = min(start + config.slide_max_tokens, len(spans))
            piece = text[spans[start][0]:spans[end - 1][1]].strip()
            chunks.append(Chunk(text=piece, page_no=page_no, part=part, token_count=end - start))
            if end == len(spans):
                break
            start, part = end - config.slide_overlap_tokens, part + 1
    return chunks


def chunk_utterances(segments: Sequence[tuple[int, int, str]],
                     seconds: int = DEFAULT_CONFIG.utterance_chunk_seconds) -> list[Chunk]:
    """확정 발화 (start_ms, end_ms, text) 목록을 30초 단위 조각으로 묶는다.

    - start_ms 순으로 정렬해서 본다. 조각의 시작 = 첫 발화의 start_ms.
    - 다음 발화의 start_ms가 (조각 시작 + seconds*1000) 이상이면 새 조각을 연다. 발화 하나는 쪼개지 않는다.
    - text = 발화 text를 strip해서 공백 하나로 이은 것. 빈 발화는 건너뛴다. end_ms = 조각 마지막 발화의 end_ms.
    """
    window = seconds * 1000
    chunks: list[Chunk] = []
    cur: list[tuple[int, int, str]] = []
    for seg in sorted(((s, e, t.strip()) for s, e, t in segments if t and t.strip()), key=lambda x: x[0]):
        if cur and seg[0] >= cur[0][0] + window:
            chunks.append(_utterance_chunk(cur))
            cur = []
        cur.append(seg)
    if cur:
        chunks.append(_utterance_chunk(cur))
    return chunks


def _utterance_chunk(segs: list[tuple[int, int, str]]) -> Chunk:
    return Chunk(text=" ".join(t for _, _, t in segs), start_ms=segs[0][0], end_ms=segs[-1][1])
