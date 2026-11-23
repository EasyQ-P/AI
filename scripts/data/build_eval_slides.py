"""평가용 교안 조각 파일(es-vN 초안)을 만든다 (설계서 6.1.6 평가용 강의 판정, 7.4.2 등록).

ocw_slide_chunks.py 결과(slides-v3)에서 평가 강좌(검증 6.0001, 시험 6.172)의 조각만 골라
eval_reference_chunks.jsonl(lecture_id, source_key, page_no, chunk_index, text)과 meta.json을 만든다.
meta.json에는 청킹 규칙(stats.json의 rules)과 백엔드 합의 일치 판정 기준을 적는다.

사용:
    uv run python scripts/data/build_eval_slides.py --name es-draft-1
출력: data/processed/<이름>/eval_reference_chunks.jsonl, meta.json
"""

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

EVAL_COURSES = ["6.0001_F16", "6.172_F18"]
FIELDS = ["lecture_id", "source_key", "page_no", "chunk_index", "text"]
# 서비스 교안 조각과 평가용 조각이 같은지 판정하는 기준(백엔드 합의, 2026-11-24)
MATCH_CRITERIA = {
    "shingle_words": 5,
    "chunk_match_ratio": 0.8,
    "lecture_flag_ratio": 0.3,
    "note": "5단어 shingle 겹침이 80% 이상이면 같은 조각, 강의의 조각 중 30% 이상이 안 맞으면 강의에 표시",
}


def select(rows: list[dict], courses: list[str]) -> list[dict]:
    """평가 강좌 조각만, 필드를 줄여 (lecture_id, chunk_index) 순으로."""
    keep = [r for r in rows if r["course_id"] in courses]
    keep.sort(key=lambda r: (r["lecture_id"], r["chunk_index"]))
    keys = [r["source_key"] for r in keep]
    if len(keys) != len(set(keys)):
        raise ValueError("source_key가 겹침")
    return [{f: r[f] for f in FIELDS} for r in keep]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--slides", type=Path, default=Path("data/interim/mit_ocw/slides-v3"))
    ap.add_argument("--out-root", type=Path, default=Path("data/processed"))
    ap.add_argument("--courses", nargs="*", default=EVAL_COURSES)
    args = ap.parse_args()

    rows, missing = [], []
    for c in args.courses:
        p = args.slides / f"{c}.jsonl"
        if not p.is_file():
            missing.append(c)
            continue
        with open(p, encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    chunks = select(rows, args.courses)
    token_counts = [r["token_count"] for r in rows if r["course_id"] in args.courses]
    rules = json.loads((args.slides / "stats.json").read_text(encoding="utf-8"))["rules"]

    out = args.out_root / args.name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "eval_reference_chunks.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in chunks:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {
        "name": args.name,
        "created": dt.date.today().isoformat(),
        "source": str(args.slides),
        "courses": args.courses,
        "missing_courses": missing,
        "tokenizer": rules["tokenizer"],
        "max_tokens": rules["max_tokens"],
        "overlap_tokens": rules["overlap_tokens"],
        "min_chars": rules["min_chars"],
        "min_content_words": rules["min_content_words"],
        "content_words": rules.get("content_words"),
        "min_word_char_ratio": rules.get("min_word_char_ratio"),
        "min_wordlike_token_ratio": rules.get("min_wordlike_token_ratio"),
        "match_criteria": MATCH_CRITERIA,
        "counts": {
            "chunks": len(chunks),
            "lectures": len({r["lecture_id"] for r in chunks}),
            "by_course": dict(Counter(r["lecture_id"].rsplit("_", 1)[0] for r in chunks)),
            "max_chunk_tokens": max(token_counts, default=0),
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(chunks)}조각 → {out}")
    print(json.dumps(meta["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
