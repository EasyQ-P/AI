"""어려운 오답 뽑기(scripts/search/hard_negatives.py)가 읽는 검색 묶음(pack)을 만든다 (설계서 3.3.4 학습셋 5단계).

pack 구성 (ai-2 rc-v1과 같은 형식):
  dataset/train.jsonl              오답을 붙일 OCW 답변 가능 쌍(--evidence-types로 근거 종류 거르기)
  index/transcripts/<강좌>.jsonl   발화 청크 + 한국어 변환본(evidence_text_ko). 변환본이 있는 청크만.
  index/slides-v4/<강좌>.jsonl     교안 조각(slides-v4 그대로)
  meta.json

- 발화 청크는 evidence_type = TRANSCRIPT, chunk_index(evidence_id 끝 T0001 → 1)를 넣는다.
  hard_negatives.py가 evidence_type이 없으면 교안으로 보고, chunk_index로 정답 ±1 청크를 뺀다.
- 한국어 변환본은 합성 배치 output.jsonl의 ko_text에서 가져온다. 변환한 강의(학습 6강의)만 있으므로
  나머지 강의는 교안만 색인된다.
- 강좌는 train 쌍에 나온 강좌만. AI Hub 행(contains_aihub)이 있으면 멈춘다(임베딩 금지, 3.1.3).

사용 (B안 교안 답변 가능 150개에만 오답 붙이기):
    uv run python scripts/data/build_search_pack.py --train data/processed/ds-draft-2/train.jsonl \
        --evidence-types DOCUMENT --synth data/interim/synth/train-ocw-v3_1
    uv run python scripts/search/hard_negatives.py --pack data/raw/easyq_ai2_search_pack \
        --name hn-slides-v1 --embedder gemini --max-neg 3
"""

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

CHUNK_NO_RE = re.compile(r"_T(\d+)$")


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def select_targets(train: list[dict], evidence_types: set[str] | None) -> list[dict]:
    """오답을 붙일 OCW 답변 가능 쌍. AI Hub 행이 섞여 있으면 멈춘다."""
    if any(r.get("contains_aihub") for r in train):
        raise ValueError("train에 AI Hub 행이 있음. 검색 묶음(임베딩)에 넣을 수 없다(3.1.3)")
    return [
        r for r in train
        if r["source"] == "MIT_OCW" and r["label"] == "ANSWERABLE"
        and (evidence_types is None or r["evidence_type"] in evidence_types)
    ]


def ko_texts(synth_dirs: list[Path]) -> dict[str, str]:
    """합성 배치 output.jsonl → {evidence_id: ko_text}. 같은 청크가 여러 배치에 있으면 앞 배치를 쓴다."""
    out: dict[str, str] = {}
    for d in synth_dirs:
        for r in read_jsonl(d / "output.jsonl"):
            if r.get("ko_text") and r["evidence_id"] not in out:
                out[r["evidence_id"]] = r["ko_text"]
    return out


def transcript_index(chunks: list[dict], ko: dict[str, str]) -> list[dict]:
    """한국어 변환본이 있는 발화 청크만 색인 행으로."""
    rows = []
    for c in chunks:
        if c["evidence_id"] not in ko:
            continue
        m = CHUNK_NO_RE.search(c["evidence_id"])
        rows.append(
            {
                "evidence_id": c["evidence_id"],
                "lecture_id": c["lecture_id"],
                "course_id": c["course_id"],
                "evidence_type": "TRANSCRIPT",
                "chunk_index": int(m.group(1)) if m else None,
                "evidence_text": c["evidence_text"],
                "evidence_text_ko": ko[c["evidence_id"]],
            }
        )
    return rows


def build_pack(
    train: list[dict], evidence_types: set[str] | None, synth_dirs: list[Path], chunks_dir: Path,
    slides_dir: Path, out: Path,
) -> dict:
    targets = select_targets(train, evidence_types)
    if not targets:
        raise ValueError("오답을 붙일 답변 가능 쌍이 없음")
    courses = sorted({r["course_id"] for r in targets})
    ko = ko_texts(synth_dirs)
    if out.exists():
        # 이 스크립트가 만든 묶음(meta.json에 targets가 있음)만 지우고 다시 만든다. 다른 묶음이면 멈춘다.
        if not (out / "meta.json").exists() or "targets" not in json.loads((out / "meta.json").read_text("utf-8")):
            raise ValueError(f"{out}에 이 스크립트가 만들지 않은 파일이 있음. --out을 바꾸거나 직접 정리하세요")
        shutil.rmtree(out)
    write_jsonl(out / "dataset" / "train.jsonl", targets)
    counts: dict[str, dict[str, int]] = {}
    for course in courses:
        t_rows = transcript_index(read_jsonl(chunks_dir / f"{course}.jsonl"), ko)
        s_rows = read_jsonl(slides_dir / f"{course}.jsonl")
        write_jsonl(out / "index" / "transcripts" / f"{course}.jsonl", t_rows)
        write_jsonl(out / "index" / "slides-v4" / f"{course}.jsonl", s_rows)
        counts[course] = {"transcripts": len(t_rows), "slides": len(s_rows),
                          "transcript_lectures": len({r["lecture_id"] for r in t_rows})}
    # 대상 질문의 강의에 발화 색인이 있는지(없으면 그 질문의 오답은 교안에서만 나온다)
    indexed_lectures = {
        r["lecture_id"] for course in courses
        for r in read_jsonl(out / "index" / "transcripts" / f"{course}.jsonl")
    }
    meta = {
        "created": dt.date.today().isoformat(),
        "targets": len(targets),
        "targets_by_evidence_type": dict(Counter(r["evidence_type"] for r in targets)),
        "targets_by_course": dict(Counter(r["course_id"] for r in targets)),
        "targets_without_transcript_index": sum(r["lecture_id"] not in indexed_lectures for r in targets),
        "index": counts,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--train", type=Path, required=True, help="build_splits.py의 train.jsonl")
    ap.add_argument("--evidence-types", nargs="*", default=None,
                    help="이 근거 종류의 답변 가능 쌍에만 오답을 붙인다(예: DOCUMENT). 없으면 전부")
    ap.add_argument("--synth", type=Path, nargs="+", required=True, help="한국어 변환본이 있는 합성 배치 폴더")
    ap.add_argument("--chunks", type=Path, default=Path("data/interim/mit_ocw/chunks"))
    ap.add_argument("--slides", type=Path, default=Path("data/interim/mit_ocw/slides-v4"))
    ap.add_argument("--out", type=Path, default=Path("data/raw/easyq_ai2_search_pack"))
    args = ap.parse_args()
    meta = build_pack(read_jsonl(args.train), set(args.evidence_types) if args.evidence_types else None,
                      args.synth, args.chunks, args.slides, args.out)
    print(f"검색 묶음 → {args.out}")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
