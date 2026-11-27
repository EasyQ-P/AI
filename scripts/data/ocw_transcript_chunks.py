"""MIT OCW 강사 발화를 30초 분량 발화 청크로 나눈다 (설계서 3.2.2 (1) 3단계, 3.3.1 2단계).

전사본에는 발화 시각이 없으므로 강의마다 '전체 단어 수 ÷ 영상 길이'로 말하는 속도를 구해
30초 분량 단어 수(목표 길이)를 정하고, 강사 발화를 문장 경계에서 그 길이에 가깝게 자른다.
(예: 분당 125단어 → 30초에 약 62단어). start_ms · end_ms는 비워 둔다(3.3.3).

입력:  ocw_transcript_text.py 결과 (<in>/transcripts/<course_id>.jsonl, <in>/lectures.jsonl)
출력:  <in>/chunks/<course_id>.jsonl  청크마다 1행
       evidence_id(<lecture_id>_T0001), lecture_id, course_id, split, evidence_type(TRANSCRIPT),
       evidence_text, evidence_lang(en), chunk_index, word_count, target_words, start_ms, end_ms

사용:
    uv run python scripts/data/ocw_transcript_chunks.py
"""

import argparse
import json
import re
import sys
from pathlib import Path

from retrieval.config import DEFAULT_CONFIG

SENTENCE_END_RE = re.compile(r"(?<=[.?!])\s+(?=\S)")
# 영상 길이를 모를 때 쓰는 말하는 속도(설계서 예시: 분당 약 125단어)
DEFAULT_WPM = 125
# 마지막 청크가 목표의 이 비율보다 짧으면 앞 청크에 붙인다.
MIN_TAIL_RATIO = 0.5


def target_words(
    total_words: int, duration_sec: int | None, seconds: int = DEFAULT_CONFIG.utterance_chunk_seconds
) -> int:
    """강의 전체 단어 수와 영상 길이로 '청크 하나(기본 30초)'에 들어갈 단어 수를 구한다."""
    wpm = total_words / (duration_sec / 60) if duration_sec else DEFAULT_WPM
    return max(1, round(wpm * seconds / 60))


def split_sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_END_RE.split(text.strip()) if s]


def chunk_words(text: str, target: int) -> list[str]:
    """문장 경계에서 목표 단어 수에 가깝게 자른다. 목표의 1.5배를 넘는 긴 문장은 단어 수로 자른다."""
    pieces: list[list[str]] = []
    for sentence in split_sentences(text):
        words = sentence.split()
        if len(words) > target * 1.5:
            pieces.extend(words[i : i + target] for i in range(0, len(words), target))
        else:
            pieces.append(words)

    chunks: list[list[str]] = []
    cur: list[str] = []
    for piece in pieces:
        if cur and len(cur) + len(piece) > target:
            # 넣었을 때와 안 넣었을 때 중 목표에 더 가까운 쪽을 고른다.
            if abs(len(cur) + len(piece) - target) < abs(len(cur) - target):
                cur.extend(piece)
                chunks.append(cur)
                cur = []
                continue
            chunks.append(cur)
            cur = []
        cur.extend(piece)
    if cur:
        if chunks and len(cur) < target * MIN_TAIL_RATIO:
            chunks[-1].extend(cur)
        else:
            chunks.append(cur)
    return [" ".join(c) for c in chunks]


def chunk_lecture(row: dict, meta: dict) -> list[dict]:
    total = sum(meta["words_by_role"].values())
    target = target_words(total, meta.get("duration_sec"))
    return [
        {
            "evidence_id": f"{row['lecture_id']}_T{i:04d}",
            "lecture_id": row["lecture_id"],
            "course_id": row["course_id"],
            "split": meta["split"],
            "source": "MIT_OCW",
            "evidence_type": "TRANSCRIPT",
            "evidence_text": text,
            "evidence_lang": "en",
            "chunk_index": i,
            "word_count": len(text.split()),
            "target_words": target,
            "start_ms": None,
            "end_ms": None,
        }
        for i, text in enumerate(chunk_words(row["text"], target), start=1)
    ]


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="in_dir", type=Path, default=Path("data/interim/mit_ocw"))
    args = parser.parse_args()

    metas = {m["lecture_id"]: m for m in read_jsonl(args.in_dir / "lectures.jsonl")}
    out_dir = args.in_dir / "chunks"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((args.in_dir / "transcripts").glob("*.jsonl")):
        chunks = []
        for row in read_jsonl(path):
            chunks.extend(chunk_lecture(row, metas[row["lecture_id"]]))
        with open(out_dir / path.name, "w", encoding="utf-8", newline="\n") as fh:
            for c in chunks:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")
        sizes = sorted(c["word_count"] for c in chunks)
        median = sizes[len(sizes) // 2] if sizes else 0
        print(f"{path.stem:12} 청크 {len(chunks):6,}개  단어 수 중앙값 {median:3}  (최소 {sizes[0]}, 최대 {sizes[-1]})")


if __name__ == "__main__":
    main()
