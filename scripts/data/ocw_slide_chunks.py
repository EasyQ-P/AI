"""MIT OCW 교안(슬라이드 · 강의 노트 PDF/PPTX)을 쪽 단위 교안 조각으로 나눈다 (설계서 3.2.3, 회의안건 B4).

규칙 (백엔드 합의안, 2026-11-24)
- 1쪽 = 1조각 단위. 쪽을 넘겨 붙이지 않는다. PPTX는 슬라이드 1장 = 1쪽, 발표자 노트는 읽지 않는다.
- 조각 최대 400토큰(bge-reranker-v2-m3 토크나이저, 특수 토큰 제외). 넘으면 문단 → 문장 → 토큰 순으로 나눈다.
- 한 쪽을 여러 조각으로 나눌 때만 이웃 조각이 약 50토큰 겹친다: 앞 조각의 마지막 약 50토큰을 다음 조각 앞에 붙인다
  (토큰 위치에서 자르되 단어 중간이면 다음 단어 처음부터). 겹친 부분을 포함해도 400토큰 이하. 쪽 사이에는 겹치지 않는다.
- 내용이 적은 쪽은 조각을 만들지 않고(다음 쪽에 붙이지도 않음) 개수만 기록한다:
  정리한 글이 20자 미만이거나 내용어가 3개 미만인 쪽.
  내용어 = Kiwi(kiwipiepy) 명사(NNG · NNP) 개수 + 라틴 문자 단어(정규식 [A-Za-z][A-Za-z0-9]+) 개수.
  (Kiwi SL 태그 대신 정규식을 쓴다: 한 글자 변수(x, n)는 세지 않고, 영어 교안에서 결과가 Kiwi 버전에 덜 흔들린다.)
- 제3자 저작물 표시(© ... All rights reserved, "excluded from our Creative Commons license")가 있는 문단은 뺀다.
- 6.172 저작권 줄(© 2008–2018 by the MIT 6.172 Lecturers 등)은 지운다. (2026-11-24 추가)
- 깨진 글 줄을 뺀다(6.172 일부 글꼴이 !"#$%& 같은 기호로 뽑힘). 글상자 안의 줄마다,
  괄호 · = · 따옴표 · 쉼표 · 콜론을 뺀 글자 중 글자 · 숫자 비율이 0.5 미만이거나
  단어처럼 보이는 토큰이 절반 미만이면 깨진 줄로 본다. 내용 적은 쪽 판정 전에 한다.
- 필드: lecture_id, source_key, page_no, chunk_index, text (+ 확인용 course_id, split, token_count, source_file)
  source_key = <lecture_id>_D<쪽>_<쪽 안 번호>  (회의안건 B4 임시안)
  chunk_index = 문서 안에서 1부터 매긴 순서

입력:  data/raw/mit_ocw/<강좌 폴더>/<zip>  (강좌 "Download Course" zip, 압축을 풀지 않고 읽는다)
       data/interim/mit_ocw/lectures.jsonl  (lecture_id · split 확인용)
출력:  data/interim/mit_ocw/slides-v4/<course_id>.jsonl, data/interim/mit_ocw/slides-v4/stats.json
       (이전 결과 slides/ · slides-v2/ · slides-v3/는 그대로 둔다)

사용:
    uv run python scripts/data/ocw_slide_chunks.py                       # 학습 · 검증 · 시험 강좌 전부
    uv run python scripts/data/ocw_slide_chunks.py --lectures 6.006_S20_L07 6.006_S20_L13
    uv run python scripts/data/ocw_slide_chunks.py --tokenizer <토크나이저 폴더 또는 tokenizer.json>
"""

import argparse
import io
import json
import re
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

MAX_TOKENS = 400
OVERLAP_TOKENS = 50
MIN_CHARS = 20
MIN_CONTENT_WORDS = 3
TOKENIZER = "BAAI/bge-reranker-v2-m3"

# 강좌 zip 안 파일 이름 → (lecture 번호, 문서 표시). 강의(L) 교안만 쓴다(레시테이션 · 문제 풀이 노트 제외).
COURSE_DIRS = {
    "6.006_S20": "6-006-introduction-to-algorithms-spring-2020",
    "6.034_F10": "6-034-artificial-intelligence-fall-2010",
    "6.046J_S15": "6-046j-design-and-analysis-of-algorithms-spring-2015",
    "6.0001_F16": "6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016",
    "6.172_F18": "6-172-performance-engineering-of-software-systems-fall-2018",
}
DOC_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "6.006_S20": [(re.compile(r"mit6_006s20_lec(\d+)\.pdf$", re.I), "D")],
    # writtenlecN(필기 노트)은 스캔 이미지라 글자가 거의 없어 쓰지 않는다(쪽 대부분이 내용 적은 쪽).
    "6.046J_S15": [(re.compile(r"MIT6_046JS15_lec(\d+)\.pdf$", re.I), "D")],
    "6.0001_F16": [(re.compile(r"MIT6_0001F16_Lec(\d+)\.pdf$", re.I), "D")],
    # 시험 강좌. lecN만(rec · hw · quiz · project · leiserchess · 유튜브 ID 이름의 자막 PDF 제외).
    "6.172_F18": [(re.compile(r"MIT6_172F18_lec(\d+)\.pdf$", re.I), "D")],
}
# 6.034는 강의별 슬라이드가 없고 주제별 노트만 있어 강의에 직접 붙인다.
FIXED_DOCS = {
    "6.034_F10": {
        "MIT6_034F10_netmath.pdf": ("L12A", "D"),  # Neural Net Notes
        "MIT6_034F10_svm.pdf": ("L16", "D"),
        "MIT6_034F10_boosting.pdf": ("L17", "D"),
        "MIT6_034F10_bayes.pdf": ("L21", "D"),  # Probabilistic Inference Notes
    },
}

# 제3자 저작물 표시. OCW는 이런 그림 · 인용 옆에 이 문구를 붙인다.
THIRD_PARTY_RE = re.compile(
    r"all rights reserved|excluded from our creative commons license|ocw\.mit\.edu/(?:help/)?faq-fair-use",
    re.I,
)
# OCW 마지막 쪽 안내문 · 쪽 번호만 있는 문단(내용 아님)
BOILERPLATE_RE = re.compile(
    r"^(?:\d{1,3}|MIT OpenCourseWare\s+https?://ocw\.mit\.edu.*|"
    r"For information about citing these materials or our Terms of Use.*|https?://ocw\.mit\.edu.*)$",
    re.I | re.S,
)
# 6.172 교안 모든 쪽의 저작권 줄. 다른 글과 한 글상자에 섞여 나오므로 문단 단위가 아니라 글 안에서 지운다.
COPYRIGHT_RE = re.compile(
    # ©가 빠지거나 연도가 앞뒤로 흩어져 뽑히는 경우도 있다("2008-2018 by the © 2008 MIT 6.172 Lecturers 2018").
    r"(?:(?:©|\(c\))\s*)?(?:\d{4}(?:\s*[–—-]\s*\d{4})?\s*)?(?:by\s+the\s+)?(?:©\s*\d{4}\s*)?"
    r"(?:MIT\s+6\.172\s+Lecturers|Lecturers\s+of\s+MIT\s+6\.172)(?:\s+\d{4}(?:\s+\d{4})?\b)?",
    re.I,
)
# 깨진 글 판정(6.172 PDF 일부 글꼴은 글자 대응표가 없어 !"#$%& 같은 기호로 뽑힌다). 줄마다 본다.
MIN_WORD_CHAR_RATIO = 0.5
MIN_WORDLIKE_TOKEN_RATIO = 0.5
CODE_BRACKETS = set("()[]{}='\",:")  # 비율을 셀 때 빼는 글자: 괄호 · = · 따옴표 · 쉼표 · 콜론(코드 줄 보존)
SENTENCE_END_RE = re.compile(r"(?<=[.?!])\s+(?=\S)")
# PDF 글머리표 글꼴(사용자 정의 영역) · 제어 문자
JUNK_RE = re.compile(r"[\ue000-\uf8ff\x00-\x08\x0b-\x1f]")
WS_RE = re.compile("[ \t\u00a0]+")


LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
KIWI_NOUN_TAGS = ("NNG", "NNP")


class TokenCounter:
    """토크나이저(기본 bge-reranker-v2-m3)로 토큰 수를 세고, 긴 문장을 토큰 단위로 자르고, 끝 토큰을 떼어 낸다."""

    def __init__(self, name_or_path: str = TOKENIZER):
        from tokenizers import Tokenizer

        p = Path(name_or_path)
        if p.is_dir():
            p = p / "tokenizer.json"
        self.tok = Tokenizer.from_file(str(p)) if p.is_file() else Tokenizer.from_pretrained(name_or_path)

    def count(self, text: str) -> int:
        return len(self.tok.encode(text, add_special_tokens=False).ids)

    def split(self, text: str, max_tokens: int) -> list[str]:
        offsets = self.tok.encode(text, add_special_tokens=False).offsets
        return [
            text[offsets[i][0] : offsets[min(i + max_tokens, len(offsets)) - 1][1]].strip()
            for i in range(0, len(offsets), max_tokens)
        ]

    def tail(self, text: str, n: int) -> str:
        """text의 마지막 약 n토큰. 자른 곳이 단어 중간이면 다음 단어 처음부터(그래서 n보다 조금 적을 수 있다)."""
        offsets = self.tok.encode(text, add_special_tokens=False).offsets
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


def content_word_count(text: str) -> int:
    """내용어 수 = Kiwi 명사(NNG · NNP) + 라틴 문자 단어([A-Za-z][A-Za-z0-9]+)."""
    nouns = sum(t.tag in KIWI_NOUN_TAGS for t in _kiwi().tokenize(text)) if re.search(r"[가-힣]", text) else 0
    return nouns + len(LATIN_WORD_RE.findall(text))


_KIWI = None


def _kiwi():
    global _KIWI
    if _KIWI is None:
        from kiwipiepy import Kiwi

        _KIWI = Kiwi()
    return _KIWI


def is_low_content(
    text: str,
    content_words: Callable[[str], int] = content_word_count,
    min_chars: int = MIN_CHARS,
    min_content_words: int = MIN_CONTENT_WORDS,
) -> bool:
    """글이 min_chars자 미만이거나 내용어가 min_content_words개 미만이면 True. 글자 수는 공백을 하나로 줄여 센다."""
    flat = re.sub(r"\s+", " ", text).strip()
    return len(flat) < min_chars or content_words(flat) < min_content_words


def clean_block(text: str) -> str:
    """PDF 글상자 하나 → 한 문단. 줄 끝 하이픈을 잇고 공백을 하나로."""
    text = JUNK_RE.sub(" ", re.sub(r"(\w)-\n(\w)", r"\1\2", text))
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln)


def _word_share(s: str) -> float:
    """CODE_BRACKETS를 뺀 공백 아닌 글자 중 글자 · 숫자(str.isalnum: 라틴 · 한글 · 그리스 문자 등) 비율."""
    chars = [c for c in s if not c.isspace() and c not in CODE_BRACKETS]
    return sum(c.isalnum() for c in chars) / len(chars) if chars else 1.0


def is_garbled(
    line: str,
    min_word_char_ratio: float = MIN_WORD_CHAR_RATIO,
    min_wordlike_token_ratio: float = MIN_WORDLIKE_TOKEN_RATIO,
) -> bool:
    """깨진 글 줄이면 True.

    - 글자 · 숫자 비율(괄호 · = · 따옴표 · 쉼표 · 콜론 제외)이 min_word_char_ratio 미만이거나
    - 단어처럼 보이는 토큰(글자 · 숫자 비율 0.5 이상)이 min_wordlike_token_ratio 미만.
      글자 · 숫자가 없는 2글자 이하 토큰(=, +, ==, {, })은 연산자로 보고 세지 않는다.
    코드 · 수식 줄(x = a[i], L[i] = L[i] + 1, O(n log n))은 통과한다.
    """
    if not line.strip():
        return False
    if _word_share(line) < min_word_char_ratio:
        return True
    toks = [t for t in line.split() if any(c.isalnum() for c in t) or len(t) > 2]
    if not toks:
        return False
    wordlike = sum(_word_share(t) >= 0.5 for t in toks)
    return wordlike / len(toks) < min_wordlike_token_ratio


def strip_garbled(
    block: str,
    min_word_char_ratio: float = MIN_WORD_CHAR_RATIO,
    min_wordlike_token_ratio: float = MIN_WORDLIKE_TOKEN_RATIO,
) -> tuple[str, int]:
    """글상자에서 저작권 줄을 지우고 깨진 줄을 뺀다. (남은 글, 뺀 깨진 줄 수)"""
    lines = COPYRIGHT_RE.sub(" ", block).splitlines()
    kept = [ln for ln in lines if not is_garbled(ln, min_word_char_ratio, min_wordlike_token_ratio)]
    dropped = sum(1 for ln in lines if ln.strip()) - sum(1 for ln in kept if ln.strip())
    return "\n".join(kept), dropped


def page_paragraphs(
    blocks: list[str],
    min_word_char_ratio: float = MIN_WORD_CHAR_RATIO,
    min_wordlike_token_ratio: float = MIN_WORDLIKE_TOKEN_RATIO,
) -> tuple[list[str], int, int]:
    """쪽의 문단 목록에서 저작권 줄 · 깨진 줄 · 제3자 저작물 표시 문단 · 안내문을 뺀다.

    반환: (남은 문단, 뺀 제3자 표시 문단 수, 뺀 깨진 줄 수). 깨진 글은 PDF 글상자 안의 줄 단위로 뺀다
    (한 글상자에 깨진 줄과 제목이 섞여 나오기 때문).
    """
    kept, removed, garbled = [], 0, 0
    for b in blocks:
        b, g = strip_garbled(b, min_word_char_ratio, min_wordlike_token_ratio)
        garbled += g
        b = clean_block(b)
        if not b or BOILERPLATE_RE.match(b):
            continue
        if THIRD_PARTY_RE.search(b):
            removed += 1
            continue
        kept.append(b)
    return kept, removed, garbled


def pack(units: list[str], count: Callable[[str], int], max_tokens: int, sep: str) -> list[str]:
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


def chunk_page(
    paragraphs: list[str],
    count: Callable[[str], int],
    split_tokens: Callable[[str, int], list[str]],
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = 0,
    tail: Callable[[str, int], str] | None = None,
) -> list[str]:
    """한 쪽을 조각으로. 쪽 전체가 max_tokens 이하면 1조각, 넘으면 문단 → 문장 → 토큰 순으로 나눈다.

    나눌 때는 (max_tokens - overlap_tokens) 안으로 나눈 뒤, 둘째 조각부터 앞 조각의 끝 약 overlap_tokens를 앞에 붙인다.
    붙인 결과가 max_tokens를 넘으면(토큰 경계가 합쳐지며 늘어난 경우) 겹침을 줄인다.
    """
    whole = "\n".join(paragraphs)
    if count(whole) <= max_tokens:
        return [whole] if whole else []
    if overlap_tokens and tail is None:
        raise ValueError("overlap_tokens를 쓰려면 tail 함수가 필요함")
    if not 0 <= overlap_tokens < max_tokens // 2:
        raise ValueError(f"overlap_tokens {overlap_tokens}는 max_tokens {max_tokens}의 절반보다 작아야 함")
    budget = max_tokens - overlap_tokens
    pieces = []
    for para in pack(paragraphs, count, budget, "\n"):
        if count(para) <= budget:
            pieces.append(para)
            continue
        sentences = [s for line in para.split("\n") for s in SENTENCE_END_RE.split(line) if s]
        for sent_group in pack(sentences, count, budget, " "):
            if count(sent_group) <= budget:
                pieces.append(sent_group)
            else:
                pieces.extend(split_tokens(sent_group, budget))
    pieces = [p for p in pieces if p.strip()]
    if not overlap_tokens:
        return pieces
    out = pieces[:1]
    for prev, cur in zip(pieces, pieces[1:], strict=False):
        n = overlap_tokens
        while n > 0:
            head = tail(prev, n)
            joined = f"{head} {cur}" if head else cur
            if count(joined) <= max_tokens:
                break
            n -= 5
        else:
            joined = cur
        out.append(joined)
    return out


def read_pdf_pages(data: bytes) -> list[list[str]]:
    """PDF → 쪽마다 글상자(문단) 텍스트 목록. 위에서 아래, 왼쪽에서 오른쪽 순서."""
    import pymupdf

    pages = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0]  # 6: 0=글, 1=그림
            pages.append([b[4] for b in blocks])
    return pages


A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def read_pptx_pages(data: bytes) -> list[list[str]]:
    """PPTX → 슬라이드마다 문단 텍스트 목록. ppt/slides/slideN.xml만 읽어 발표자 노트(notesSlides)는 빠진다."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(
            (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
        )
        pages = []
        for n in names:
            root = ElementTree.fromstring(z.read(n))
            paras = ["".join(t.text or "" for t in p.iter(f"{A_NS}t")) for p in root.iter(f"{A_NS}p")]
            pages.append([p for p in paras if p.strip()])
    return pages


def find_docs(course_id: str, names: list[str]) -> list[tuple[str, str, str]]:
    """zip 안 파일 이름 → [(파일 이름, lecture_id, 문서 표시)]. 강의 교안이 아닌 파일은 뺀다."""
    found = []
    for name in names:
        base = name.rsplit("/", 1)[-1]
        stem = re.sub(r"^[0-9a-f]{32}_", "", base)
        if course_id in FIXED_DOCS and stem in FIXED_DOCS[course_id]:
            lec, tag = FIXED_DOCS[course_id][stem]
            found.append((name, f"{course_id}_{lec}", tag))
            continue
        for pat, tag in DOC_PATTERNS.get(course_id, []):
            if m := pat.search(stem):
                found.append((name, f"{course_id}_L{int(m.group(1)):02d}", tag))
                break
    # 같은 교안이 이름만 달리 두 번 든 경우(예: 6.006 lec18) 하나만 쓴다.
    unique = {}
    for name, lecture_id, tag in sorted(found, key=lambda x: (x[1], x[2], x[0])):
        unique.setdefault((lecture_id, tag), (name, lecture_id, tag))
    return list(unique.values())


def chunk_document(
    pages: list[list[str]],
    lecture_id: str,
    tag: str,
    count: Callable[[str], int],
    split_tokens: Callable[[str, int], list[str]],
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = 0,
    tail: Callable[[str, int], str] | None = None,
    content_words: Callable[[str], int] = content_word_count,
    min_chars: int = MIN_CHARS,
    min_content_words: int = MIN_CONTENT_WORDS,
    min_word_char_ratio: float = MIN_WORD_CHAR_RATIO,
    min_wordlike_token_ratio: float = MIN_WORDLIKE_TOKEN_RATIO,
) -> tuple[list[dict], dict]:
    """page_count는 모든 쪽, chunk_count는 만든 조각 수(내용 적은 쪽 제외), excluded_low_content는 뺀 쪽 수."""
    rows = []
    stats = {"page_count": len(pages), "excluded_low_content": 0, "garbled_blocks": 0,
             "third_party_blocks": 0, "split_pages": 0}
    for page_no, blocks in enumerate(pages, start=1):
        paras, removed, garbled = page_paragraphs(blocks, min_word_char_ratio, min_wordlike_token_ratio)
        stats["garbled_blocks"] += garbled
        stats["third_party_blocks"] += removed
        text = "\n".join(paras)
        if is_low_content(text, content_words, min_chars, min_content_words):
            stats["excluded_low_content"] += 1
            continue
        pieces = chunk_page(paras, count, split_tokens, max_tokens, overlap_tokens, tail)
        if len(pieces) > 1:
            stats["split_pages"] += 1
        for part, piece in enumerate(pieces, start=1):
            rows.append(
                {
                    "lecture_id": lecture_id,
                    "source_key": f"{lecture_id}_{tag}{page_no}_{part}",
                    "page_no": page_no,
                    "chunk_index": len(rows) + 1,
                    "text": piece,
                    "token_count": count(piece),
                }
            )
    stats["chunk_count"] = len(rows)
    stats["max_chunk_tokens"] = max((r["token_count"] for r in rows), default=0)
    return rows, stats


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=Path("data/raw/mit_ocw"))
    ap.add_argument("--lectures-meta", type=Path, default=Path("data/interim/mit_ocw/lectures.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("data/interim/mit_ocw/slides-v4"))
    ap.add_argument("--courses", nargs="*", default=list(COURSE_DIRS))
    ap.add_argument("--lectures", nargs="*", default=None, help="이 lecture_id만 (기본: 교안이 있는 강의 전부)")
    ap.add_argument("--tokenizer", default=TOKENIZER)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--overlap-tokens", type=int, default=OVERLAP_TOKENS)
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    ap.add_argument("--min-content-words", type=int, default=MIN_CONTENT_WORDS)
    ap.add_argument("--min-word-char-ratio", type=float, default=MIN_WORD_CHAR_RATIO)
    ap.add_argument("--min-wordlike-token-ratio", type=float, default=MIN_WORDLIKE_TOKEN_RATIO)
    args = ap.parse_args()

    tc = TokenCounter(args.tokenizer)
    meta = {}
    with open(args.lectures_meta, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                meta[r["lecture_id"]] = r
    args.out.mkdir(parents=True, exist_ok=True)
    all_stats = {
        "rules": {
            "tokenizer": args.tokenizer,
            "max_tokens": args.max_tokens,
            "overlap_tokens": args.overlap_tokens,
            "min_chars": args.min_chars,
            "min_content_words": args.min_content_words,
            "content_words": "Kiwi NNG+NNP + Latin [A-Za-z][A-Za-z0-9]+",
            "min_word_char_ratio": args.min_word_char_ratio,
            "min_wordlike_token_ratio": args.min_wordlike_token_ratio,
            "garbled_unit": "line in PDF text block",
            "garbled_ignored_chars": "".join(sorted(CODE_BRACKETS)),
            "copyright_removed": "6.172 (c) YYYY-YYYY by the MIT 6.172 Lecturers",
        },
        "documents": [],
        "unmatched_lectures": [],
    }
    for course_id in args.courses:
        zips = list((args.raw / COURSE_DIRS[course_id]).glob("*.zip"))
        if not zips:
            print(f"{course_id}: zip 없음, 건너뜀")
            continue
        rows = []
        with zipfile.ZipFile(zips[0]) as z:
            docs = find_docs(course_id, z.namelist())
            for name, lecture_id, tag in docs:
                if args.lectures is not None and lecture_id not in args.lectures:
                    continue
                if lecture_id not in meta:
                    all_stats["unmatched_lectures"].append({"file": name, "lecture_id": lecture_id})
                    continue
                data = z.read(name)
                pages = read_pptx_pages(data) if name.lower().endswith(".pptx") else read_pdf_pages(data)
                doc_rows, st = chunk_document(
                    pages, lecture_id, tag, tc.count, tc.split, args.max_tokens, args.overlap_tokens, tc.tail,
                    min_chars=args.min_chars, min_content_words=args.min_content_words,
                    min_word_char_ratio=args.min_word_char_ratio,
                    min_wordlike_token_ratio=args.min_wordlike_token_ratio,
                )
                for r in doc_rows:
                    r.update(course_id=course_id, split=meta[lecture_id]["split"], source_file=name.rsplit("/", 1)[-1])
                rows.extend(doc_rows)
                all_stats["documents"].append({"lecture_id": lecture_id, "tag": tag, "file": name, **st})
                print(
                    f"{lecture_id} {tag}: {st['page_count']}쪽 → {st['chunk_count']}조각 "
                    f"(내용 적은 쪽 {st['excluded_low_content']}, 나눈 쪽 {st['split_pages']}, "
                    f"깨진 줄 {st['garbled_blocks']}, 제3자 표시 {st['third_party_blocks']}, "
                    f"최대 {st['max_chunk_tokens']}토큰)"
                )
        if rows:
            with open(args.out / f"{course_id}.jsonl", "w", encoding="utf-8", newline="\n") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (args.out / "stats.json").write_text(json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
