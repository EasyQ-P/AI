"""학습셋 무작위 10% 사람 검수표를 만들고, 검수 결과로 라벨 오류율을 센다 (설계서 3.3.1 · 3.3.5).

- 대상: train.jsonl의 OCW 합성 쌍(label_source LLM, 어려운 오답 제외). SQuAD · AI Hub는 공개 라벨이라 제외.
- 뽑기: (근거 종류, 라벨)마다 --ratio(기본 10%)씩 seed로 뽑아 비율을 그대로 둔다. 같은 입력이면 같은 결과.
- 검수표: CSV(UTF-8 BOM, 엑셀 · 구글 시트에서 바로 열림). 사람이 '판정'(O/X)과 '맞는 라벨' · '메모'를 채운다.
  answer_hint(합성 때 LLM이 적은 근거 한 줄)는 --synth 배치의 pairs.jsonl에서 가져와 참고용으로 붙인다.
- summary: 채운 검수표 → 라벨 · 근거 종류별 오류율, X 목록. meta.json에 남긴다.

사용:
    uv run python scripts/data/review_sample.py make --train data/processed/ds-draft-2/train.jsonl \
        --synth data/interim/synth/train-ocw-v3_1 data/interim/synth/train-slides-v1 --name train-10pct
    uv run python scripts/data/review_sample.py summary --name train-10pct
출력: data/interim/review/<이름>/review.csv, meta.json
"""

import argparse
import csv
import datetime as dt
import json
import random
import sys
from collections import Counter
from pathlib import Path

COLUMNS = ["no", "pair_id", "evidence_type", "label", "question_type", "question_text", "evidence_text",
           "answer_hint", "판정(O/X)", "맞는 라벨", "메모"]
LABEL_GUIDE = ("O = 라벨이 맞음, X = 틀림(맞는 라벨에 ANSWERABLE / INSUFFICIENT_EVIDENCE / OPINION). "
               "근거 하나만 보고 판단, 한 단계 추론까지 답변 가능, 일부만 답하면 근거 부족(표 3.8)")


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def review_pool(train: list[dict]) -> list[dict]:
    if any(r.get("contains_aihub") for r in train):
        raise ValueError("train에 AI Hub 행이 있음. 검수표(PC)로 꺼내지 않는다(3.1.3)")
    return [r for r in train if r["source"] == "MIT_OCW" and r["label_source"] == "LLM"
            and not r.get("is_hard_negative")]


def sample(pool: list[dict], ratio: float, seed: int) -> list[dict]:
    """(근거 종류, 라벨)마다 ratio만큼(반올림, 최소 1). 결과는 근거 종류 · 라벨 · pair_id 순."""
    rng = random.Random(seed)
    groups: dict[tuple, list[str]] = {}
    for r in pool:
        groups.setdefault((r["evidence_type"], r["label"]), []).append(r["pair_id"])
    keep = set()
    for key in sorted(groups):
        ids = sorted(groups[key])
        keep.update(rng.sample(ids, max(1, round(len(ids) * ratio))))
    picked = [r for r in pool if r["pair_id"] in keep]
    return sorted(picked, key=lambda r: (r["evidence_type"], r["label"], r["pair_id"]))


def hints(synth_dirs: list[Path]) -> dict[str, str]:
    out = {}
    for d in synth_dirs:
        for p in read_jsonl(d / "pairs.jsonl"):
            out[p["pair_id"]] = p.get("answer_hint", "")
    return out


def make(train: list[dict], synth_dirs: list[Path], ratio: float, seed: int, out: Path) -> dict:
    picked = sample(review_pool(train), ratio, seed)
    hint = hints(synth_dirs)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "review.csv"
    if csv_path.exists():
        raise ValueError(f"{csv_path}가 이미 있음(검수 내용 덮어쓰기 방지). --name을 바꾸세요")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for i, r in enumerate(picked, start=1):
            w.writerow([i, r["pair_id"], r["evidence_type"], r["label"], r.get("question_type") or "",
                        r["question_text"], r["evidence_text"], hint.get(r["pair_id"], ""), "", "", ""])
    meta = {
        "created": dt.date.today().isoformat(),
        "ratio": ratio,
        "seed": seed,
        "rows": len(picked),
        "by_type_label": {f"{t}/{lab}": n for (t, lab), n in
                          sorted(Counter((r["evidence_type"], r["label"]) for r in picked).items())},
        "guide": LABEL_GUIDE,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def summary(out: Path) -> dict:
    with open(out / "review.csv", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    judged = [r for r in rows if r["판정(O/X)"].strip().upper() in ("O", "X")]
    wrong = [r for r in judged if r["판정(O/X)"].strip().upper() == "X"]

    def rate(rs: list[dict]) -> dict:
        x = sum(r["판정(O/X)"].strip().upper() == "X" for r in rs)
        return {"n": len(rs), "x": x, "error_rate": round(x / len(rs), 3) if rs else None}

    result = {
        "rows": len(rows),
        "judged": len(judged),
        "overall": rate(judged),
        "by_label": {lab: rate([r for r in judged if r["label"] == lab])
                     for lab in sorted({r["label"] for r in judged})},
        "by_evidence_type": {t: rate([r for r in judged if r["evidence_type"] == t])
                             for t in sorted({r["evidence_type"] for r in judged})},
        "wrong": [{"pair_id": r["pair_id"], "label": r["label"], "correct": r["맞는 라벨"].strip(),
                   "memo": r["메모"].strip()} for r in wrong],
    }
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["summary"] = {"date": dt.date.today().isoformat(), **result}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("data/interim/review"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--train", type=Path, required=True)
    m.add_argument("--synth", type=Path, nargs="*", default=[], help="answer_hint를 가져올 합성 배치 폴더")
    m.add_argument("--name", required=True)
    m.add_argument("--ratio", type=float, default=0.1)
    m.add_argument("--seed", type=int, default=20261126)
    s = sub.add_parser("summary")
    s.add_argument("--name", required=True)
    args = ap.parse_args()
    out = args.root / args.name
    if args.cmd == "make":
        meta = make(read_jsonl(args.train), args.synth, args.ratio, args.seed, out)
        print(f"검수표 {meta['rows']}행 → {out / 'review.csv'}")
        print(json.dumps(meta["by_type_label"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary(out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
