"""MIT OCW 교안(슬라이드 · 강의 노트 PDF/PPTX)을 쪽 단위 교안 조각으로 나눈다 (설계서 3.2.3, 회의안건 B4).

규칙 (2026-11-21 확정)
- 1쪽 = 1조각. 쪽을 넘겨 붙이지 않고, 조각끼리 겹치지 않는다. PPTX는 슬라이드 1장 = 1쪽, 발표자 노트는 읽지 않는다.
- 조각 최대 약 350토큰(bge-m3 토크나이저, 특수 토큰 제외). 넘으면 문단 → 문장 → 토큰 순으로 나눈다.
- 10토큰 미만인 쪽은 조각을 만들지 않고 개수만 기록한다.
- 제3자 저작물 표시(© ... All rights reserved, "excluded from our Creative Commons license")가 있는 문단은 뺀다.
- 필드: lecture_id, source_key, page_no, chunk_index, text (+ 확인용 course_id, split, token_count, source_file)
  source_key = <lecture_id>_D<쪽>_<쪽 안 번호>  (회의안건 B4 임시안)
  chunk_index = 문서 안에서 1부터 매긴 순서

입력:  data/raw/mit_ocw/<강좌 폴더>/<zip>  (강좌 "Download Course" zip, 압축을 풀지 않고 읽는다)
       data/interim/mit_ocw/lectures.jsonl  (lecture_id · split 확인용)
출력:  data/interim/mit_ocw/slides/<course_id>.jsonl, data/interim/mit_ocw/slides/stats.json

사용:
    uv run python scripts/data/ocw_slide_chunks.py                       # 학습 · 검증 강좌 전부
    uv run python scripts/data/ocw_slide_chunks.py --lectures 6.006_S20_L07 6.006_S20_L13
    uv run python scripts/data/ocw_slide_chunks.py --tokenizer <bge-m3 폴더 또는 tokenizer.json>
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

MAX_TOKENS = 350
MIN_PAGE_TOKENS = 10
TOKENIZER = "BAAI/bge-m3"

# 강좌 zip 안 파일 이름 → (lecture 번호, 문서 표시). 강의(L) 교안만 쓴다(레시테이션 · 문제 풀이 노트 제외).
COURSE_DIRS = {
    "6.006_S20": "6-006-introduction-to-algorithms-spring-2020",
    "6.034_F10": "6-034-artificial-intelligence-fall-2010",
    "6.046J_S15": "6-046j-design-and-analysis-of-algorithms-spring-2015",
    "6.0001_F16": "6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016",
}
DOC_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "6.006_S20": [(re.compile(r"mit6_006s20_lec(\d+)\.pdf$", re.I), "D")],
    # writtenlecN(필기 노트)은 스캔 이미지라 글자가 거의 없어 쓰지 않는다(쪽 대부분이 10토큰 미만).
    "6.046J_S15": [(re.compile(r"MIT6_046JS15_lec(\d+)\.pdf$", re.I), "D")],
    "6.0001_F16": [(re.compile(r"MIT6_0001F16_Lec(\d+)\.pdf$", re.I), "D")],
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
SENTENCE_END_RE = re.compile(r"(?<=[.?!])\s+(?=\S)")
# PDF 글머리표 글꼴(사용자 정의 영역) · 제어 문자
JUNK_RE = re.compile(r"[\ue000-\uf8ff\x00-\x08\x0b-\x1f]")
WS_RE = re.compile("[ \t\u00a0]+")


class TokenCounter:
    """bge-m3 토크나이저로 토큰 수를 세고, 긴 문장을 토큰 단위로 자른다."""

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


def clean_block(text: str) -> str:
    """PDF 글상자 하나 → 한 문단. 줄 끝 하이픈을 잇고 공백을 하나로."""
    text = JUNK_RE.sub(" ", re.sub(r"(\w)-\n(\w)", r"\1\2", text))
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln)


def page_paragraphs(blocks: list[str]) -> tuple[list[str], int]:
    """쪽의 문단 목록에서 제3자 저작물 표시 문단과 안내문을 뺀다. (남은 문단, 뺀 제3자 표시 문단 수)"""
    kept, removed = [], 0
    for b in blocks:
        b = clean_block(b)
        if not b or BOILERPLATE_RE.match(b):
            continue
        if THIRD_PARTY_RE.search(b):
            removed += 1
            continue
        kept.append(b)
    return kept, removed


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
) -> list[str]:
    """한 쪽을 조각으로. 쪽 전체가 max_tokens 이하면 1조각, 넘으면 문단 → 문장 → 토큰 순으로 나눈다."""
    whole = "\n".join(paragraphs)
    if count(whole) <= max_tokens:
        return [whole] if whole else []
    pieces = []
    for para in pack(paragraphs, count, max_tokens, "\n"):
        if count(para) <= max_tokens:
            pieces.append(para)
            continue
        sentences = [s for line in para.split("\n") for s in SENTENCE_END_RE.split(line) if s]
        for sent_group in pack(sentences, count, max_tokens, " "):
            if count(sent_group) <= max_tokens:
                pieces.append(sent_group)
            else:
                pieces.extend(split_tokens(sent_group, max_tokens))
    return [p for p in pieces if p.strip()]


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
    min_page_tokens: int = MIN_PAGE_TOKENS,
) -> tuple[list[dict], dict]:
    rows, stats = [], {"pages": len(pages), "short_pages": 0, "third_party_blocks": 0, "split_pages": 0}
    for page_no, blocks in enumerate(pages, start=1):
        paras, removed = page_paragraphs(blocks)
        stats["third_party_blocks"] += removed
        text = "\n".join(paras)
        if count(text) < min_page_tokens:
            stats["short_pages"] += 1
            continue
        pieces = chunk_page(paras, count, split_tokens, max_tokens)
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
    stats["chunks"] = len(rows)
    return rows, stats


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=Path("data/raw/mit_ocw"))
    ap.add_argument("--lectures-meta", type=Path, default=Path("data/interim/mit_ocw/lectures.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("data/interim/mit_ocw/slides"))
    ap.add_argument("--courses", nargs="*", default=list(COURSE_DIRS))
    ap.add_argument("--lectures", nargs="*", default=None, help="이 lecture_id만 (기본: 교안이 있는 강의 전부)")
    ap.add_argument("--tokenizer", default=TOKENIZER)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
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
        "rules": {"max_tokens": args.max_tokens, "min_page_tokens": MIN_PAGE_TOKENS, "tokenizer": args.tokenizer},
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
                doc_rows, st = chunk_document(pages, lecture_id, tag, tc.count, tc.split, args.max_tokens)
                for r in doc_rows:
                    r.update(course_id=course_id, split=meta[lecture_id]["split"], source_file=name.rsplit("/", 1)[-1])
                rows.extend(doc_rows)
                all_stats["documents"].append({"lecture_id": lecture_id, "tag": tag, "file": name, **st})
                print(
                    f"{lecture_id} {tag}: {st['pages']}쪽 → {st['chunks']}조각 "
                    f"(짧은 쪽 {st['short_pages']}, 나눈 쪽 {st['split_pages']}, 제3자 표시 {st['third_party_blocks']})"
                )
        if rows:
            with open(args.out / f"{course_id}.jsonl", "w", encoding="utf-8", newline="\n") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (args.out / "stats.json").write_text(json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
