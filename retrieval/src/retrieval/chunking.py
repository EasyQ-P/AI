"""교안 청킹(R1) · 확정 발화 30초 청킹(R2) (6.1.5). 담당: 최의찬(Claude).

교안 규칙 = 엄윤종 slides-v4(`scripts/data/ocw_slide_chunks.py`, 백엔드 합의안 2026-11-24)와 같다. rc-v1 학습 · 평가
데이터가 slides-v4 결과로 만들어졌으므로 서비스도 같은 조각을 만들어야 한다(2026-11-26 비교 후 맞춤).

1. 쪽 = 글상자(문단) 목록. 글상자마다 지울 패턴(출처별, 예: 6.172 저작권 줄)을 지우고, 깨진 줄을 빼고,
   줄 끝 하이픈을 이어 한 문단으로 만든다. 빈 문단 · 쪽 번호 · OCW 안내문 · 뺄 패턴(출처별, 예: 제3자 저작물
   표시)이 있는 문단은 버린다.
2. 남은 글(공백 정리)이 slide_min_chars 미만이거나 내용어(영단어 + 한국어 명사)가 slide_min_content_words 미만인
   쪽은 조각을 만들지 않는다(다음 쪽에 붙이지도 않는다).
3. 1쪽 = 1조각. slide_max_tokens를 넘으면 (max - overlap) 안으로 문단 → 문장 → 토큰 순으로 나누고, 둘째 조각부터
   앞 조각의 끝 약 slide_overlap_tokens 토큰(단어 경계)을 앞에 붙인다. 쪽 사이에는 겹치지 않는다.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Union

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig

# 텍스트 → 토큰마다 (시작, 끝) 문자 위치. 서비스 · 데이터셋 모두 bge 토크나이저로 센다(bge_token_spans).
TokenSpans = Callable[[str], list[tuple[int, int]]]
# 쪽 하나: 글상자(문단) 목록. 글자열 하나를 주면 빈 줄로 나눠 글상자로 본다.
Page = Union[str, Sequence[str]]

# 깨진 글 비율을 셀 때 빼는 글자(코드 줄 보존): 괄호 · = · 따옴표 · 쉼표 · 콜론
_CODE_BRACKETS = set("()[]{}='\",:")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_HANGUL = re.compile(r"[가-힣]")
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=\S)")
_JUNK = re.compile(r"[-\x00-\x08\x0b-\x1f]")   # PDF 글머리표 글꼴(사용자 정의 영역) · 제어 문자
_WS = re.compile("[ \t ]+")
# 쪽 번호만 있는 문단 · OCW 마지막 쪽 안내문(내용 아님)
_BOILERPLATE = re.compile(
    r"^(?:\d{1,3}|MIT OpenCourseWare\s+https?://ocw\.mit\.edu.*|"
    r"For information about citing these materials or our Terms of Use.*|https?://ocw\.mit\.edu.*)$",
    re.I | re.S,
)

# MIT OCW 교안 전용 패턴(학습 데이터 스크립트가 넘긴다). 서비스 교안에는 쓰지 않는다.
# 6.172 교안 모든 쪽의 저작권 줄: 글상자 안에서 지운다(다른 글과 섞여 나온다).
OCW_STRIP_PATTERNS = (
    re.compile(
        r"(?:(?:©|\(c\))\s*)?(?:\d{4}(?:\s*[–—-]\s*\d{4})?\s*)?(?:by\s+the\s+)?(?:©\s*\d{4}\s*)?"
        r"(?:MIT\s+6\.172\s+Lecturers|Lecturers\s+of\s+MIT\s+6\.172)(?:\s+\d{4}(?:\s+\d{4})?\b)?",
        re.I,
    ),
)
# 제3자 저작물 표시가 있는 문단은 통째로 뺀다.
OCW_DROP_PATTERNS = (
    re.compile(r"all rights reserved|excluded from our creative commons license|ocw\.mit\.edu/(?:help/)?faq-fair-use",
               re.I),
)


@dataclass(frozen=True)
class Chunk:
    text: str
    page_no: Optional[int] = None    # 교안 조각: 쪽 번호(1부터)
    part: Optional[int] = None       # 교안 조각: 그 쪽 안의 순번(1부터). 근거 ID = {lecture_id}_D{page_no}_{part}
    start_ms: Optional[int] = None   # 발화 조각
    end_ms: Optional[int] = None
    token_count: Optional[int] = None


@dataclass(frozen=True)
class SlideStats:
    """chunk_slides 확인용 집계(slides-v4 stats.json과 같은 이름)."""

    page_count: int
    chunk_count: int
    excluded_low_content: int
    split_pages: int
    garbled_blocks: int      # 뺀 깨진 줄 수
    third_party_blocks: int  # 뺄 패턴으로 버린 문단 수


def bge_token_spans(tokenizer_name: str = DEFAULT_CONFIG.tokenizer) -> TokenSpans:
    """Hugging Face tokenizers로 특수 토큰을 뺀 토큰 위치를 돌려주는 함수를 만든다(선택 설치 `retrieval[tokenizer]`).

    처음 부를 때 Hugging Face에서 tokenizer.json을 받는다. 로컬 경로(파일 · 폴더)를 주면 그 파일을 쓴다.
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
    path = Path(name)
    if path.is_dir():
        path = path / "tokenizer.json"
    if path.is_file():
        return Tokenizer.from_file(str(path))
    return Tokenizer.from_pretrained(name)


# ---- 줄 · 문단 정리 ----------------------------------------------------------------------

def _word_share(s: str) -> float:
    """_CODE_BRACKETS · 공백을 뺀 글자 중 글자 · 숫자(str.isalnum) 비율. 셀 글자가 없으면 1."""
    chars = [c for c in s if not c.isspace() and c not in _CODE_BRACKETS]
    return sum(c.isalnum() for c in chars) / len(chars) if chars else 1.0


def is_garbled(line: str, config: RetrievalConfig = DEFAULT_CONFIG) -> bool:
    """PDF 글자 깨짐 줄이면 True(6.172 일부 글꼴이 !"#$%& 같은 기호로 뽑힌다).

    - 글자 · 숫자 비율이 slide_min_word_char_ratio 미만이거나
    - 단어처럼 보이는 토큰(글자 · 숫자 비율 0.5 이상)이 slide_min_wordlike_token_ratio 미만.
      글자 · 숫자가 없는 2글자 이하 토큰(=, +, ==, {, })은 연산자로 보고 세지 않는다.
    코드 · 수식 줄(x = a[i], L[i] = L[i] + 1, O(n log n))은 통과한다.
    """
    if not line.strip():
        return False
    if _word_share(line) < config.slide_min_word_char_ratio:
        return True
    tokens = [t for t in line.split() if any(c.isalnum() for c in t) or len(t) > 2]
    if not tokens:
        return False
    wordlike = sum(_word_share(t) >= 0.5 for t in tokens)
    return wordlike / len(tokens) < config.slide_min_wordlike_token_ratio


def _strip_garbled(block: str, strip_patterns: Sequence[re.Pattern],
                   config: RetrievalConfig) -> tuple[str, int]:
    for pattern in strip_patterns:
        block = pattern.sub(" ", block)
    lines = block.splitlines()
    kept = [ln for ln in lines if not is_garbled(ln, config)]
    dropped = sum(1 for ln in lines if ln.strip()) - sum(1 for ln in kept if ln.strip())
    return "\n".join(kept), dropped


def _clean_block(text: str) -> str:
    """글상자 하나 → 한 문단. 줄 끝 하이픈을 잇고 줄을 공백 하나로 잇는다."""
    text = _JUNK.sub(" ", re.sub(r"(\w)-\n(\w)", r"\1\2", text))
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln)


def page_paragraphs(blocks: Sequence[str], config: RetrievalConfig = DEFAULT_CONFIG,
                    strip_patterns: Sequence[re.Pattern] = (),
                    drop_patterns: Sequence[re.Pattern] = ()) -> tuple[list[str], int, int]:
    """쪽의 글상자 목록 → (남은 문단, 뺄 패턴으로 버린 문단 수, 뺀 깨진 줄 수)."""
    kept, dropped, garbled = [], 0, 0
    for block in blocks:
        block, g = _strip_garbled(block, strip_patterns, config)
        garbled += g
        block = _clean_block(block)
        if not block or _BOILERPLATE.match(block):
            continue
        if any(p.search(block) for p in drop_patterns):
            dropped += 1
            continue
        kept.append(block)
    return kept, dropped, garbled


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


def is_low_content(text: str, config: RetrievalConfig = DEFAULT_CONFIG) -> bool:
    """공백을 하나로 줄인 글이 slide_min_chars자 미만이거나 내용어가 slide_min_content_words개 미만이면 True."""
    flat = re.sub(r"\s+", " ", text).strip()
    return len(flat) < config.slide_min_chars or count_content_words(flat) < config.slide_min_content_words


# ---- 토큰 단위 나누기 --------------------------------------------------------------------

class _Tokens:
    def __init__(self, token_spans: TokenSpans):
        self.spans = token_spans

    def count(self, text: str) -> int:
        return len(self.spans(text))

    def split(self, text: str, max_tokens: int) -> list[str]:
        offsets = self.spans(text)
        return [
            text[offsets[i][0]:offsets[min(i + max_tokens, len(offsets)) - 1][1]].strip()
            for i in range(0, len(offsets), max_tokens)
        ]

    def tail(self, text: str, n: int) -> str:
        """text의 마지막 약 n토큰. 자른 곳이 단어 중간이면 다음 단어 처음부터(그래서 n보다 조금 적을 수 있다)."""
        offsets = self.spans(text)
        if n <= 0 or not offsets:
            return ""
        if n >= len(offsets):
            return text.strip()
        start = offsets[len(offsets) - n][0]
        if start > 0 and not text[start - 1].isspace():
            m = re.search(r"\s", text[start:])
            if not m:
                return ""
            start += m.end()
        return text[start:].strip()


def _pack(units: list[str], count: Callable[[str], int], max_tokens: int, sep: str) -> list[str]:
    """순서를 지키며 max_tokens를 넘지 않게 이어 붙인다. 하나가 넘치면 그대로 둔다(다음 단계에서 나눔)."""
    out, cur = [], ""
    for u in units:
        cand = f"{cur}{sep}{u}" if cur else u
        if cur and count(cand) > max_tokens:
            out.append(cur)
            cur = u
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def chunk_page(paragraphs: Sequence[str], token_spans: TokenSpans,
               config: RetrievalConfig = DEFAULT_CONFIG) -> list[str]:
    """한 쪽의 문단 → 조각 글 목록. 쪽 전체가 slide_max_tokens 이하면 1조각."""
    tok = _Tokens(token_spans)
    max_tokens, overlap = config.slide_max_tokens, config.slide_overlap_tokens
    whole = "\n".join(paragraphs)
    if tok.count(whole) <= max_tokens:
        return [whole] if whole else []
    budget = max_tokens - overlap
    pieces: list[str] = []
    for para in _pack(list(paragraphs), tok.count, budget, "\n"):
        if tok.count(para) <= budget:
            pieces.append(para)
            continue
        sentences = [s for line in para.split("\n") for s in _SENTENCE_END.split(line) if s]
        for group in _pack(sentences, tok.count, budget, " "):
            if tok.count(group) <= budget:
                pieces.append(group)
            else:
                pieces.extend(tok.split(group, budget))
    pieces = [p for p in pieces if p.strip()]
    if not overlap:
        return pieces
    out = pieces[:1]
    for prev, cur in zip(pieces, pieces[1:]):
        n = overlap
        joined = cur
        while n > 0:
            head = tok.tail(prev, n)
            candidate = f"{head} {cur}" if head else cur
            if tok.count(candidate) <= max_tokens:
                joined = candidate
                break
            n -= 5
        out.append(joined)
    return out


# ---- 교안 전체 --------------------------------------------------------------------------

def _blocks(page: Page) -> list[str]:
    if isinstance(page, str):
        return [b for b in re.split(r"\n\s*\n", page) if b.strip()]
    return list(page)


def chunk_slides_with_stats(pages: Sequence[Page], token_spans: TokenSpans,
                            config: RetrievalConfig = DEFAULT_CONFIG, *,
                            strip_patterns: Sequence[re.Pattern] = (),
                            drop_patterns: Sequence[re.Pattern] = ()) -> tuple[list[Chunk], SlideStats]:
    """chunk_slides와 같고, 쪽 · 조각 · 뺀 것 개수를 함께 돌려준다."""
    if not 0 <= config.slide_overlap_tokens < config.slide_max_tokens // 2:
        raise ValueError("slide_overlap_tokens must be smaller than half of slide_max_tokens")
    tok = _Tokens(token_spans)
    chunks: list[Chunk] = []
    low = split = garbled = dropped = 0
    for page_no, page in enumerate(pages, start=1):
        paras, d, g = page_paragraphs(_blocks(page), config, strip_patterns, drop_patterns)
        dropped += d
        garbled += g
        if is_low_content("\n".join(paras), config):
            low += 1
            continue
        pieces = chunk_page(paras, token_spans, config)
        if len(pieces) > 1:
            split += 1
        for part, piece in enumerate(pieces, start=1):
            chunks.append(Chunk(text=piece, page_no=page_no, part=part, token_count=tok.count(piece)))
    stats = SlideStats(page_count=len(pages), chunk_count=len(chunks), excluded_low_content=low,
                       split_pages=split, garbled_blocks=garbled, third_party_blocks=dropped)
    return chunks, stats


def chunk_slides(pages: Sequence[Page], token_spans: TokenSpans,
                 config: RetrievalConfig = DEFAULT_CONFIG, *,
                 strip_patterns: Sequence[re.Pattern] = (),
                 drop_patterns: Sequence[re.Pattern] = ()) -> list[Chunk]:
    """교안 쪽 목록(pages[0] = 1쪽) → 교안 조각. 빠진 쪽은 조각이 없을 뿐 쪽 번호는 원래대로 남는다.

    쪽은 글상자(문단) 목록으로 준다(PDF는 pymupdf `page.get_text("blocks", sort=True)`의 글 블록,
    PPTX는 슬라이드의 문단). 글자열 하나를 주면 빈 줄로 나눠 글상자로 본다.
    MIT OCW 교안은 strip_patterns=OCW_STRIP_PATTERNS, drop_patterns=OCW_DROP_PATTERNS를 넘긴다.
    """
    return chunk_slides_with_stats(pages, token_spans, config,
                                   strip_patterns=strip_patterns, drop_patterns=drop_patterns)[0]


# ---- 발화 --------------------------------------------------------------------------------

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
