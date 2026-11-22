"""합성 쌍(pairs.jsonl)에서 라벨 비율을 맞춰 일부를 seed로 뽑는다 (검증셋 문항 수 맞추기).

- 한 청크(evidence_id)에서 최대 1문항: 같은 근거가 여러 라벨로 겹쳐 나오지 않게.
- 라벨별 개수는 --counts로 준다(기본 ANSWERABLE 168 / INSUFFICIENT_EVIDENCE 168 / OPINION 144 = 학습 700/700/600 비율).
- 강의(lecture_id)별로 청크 수에 비례해 나눈 뒤 강의 안에서 seed로 섞어 고른다.

사용:
    uv run python scripts/data/sample_pairs.py --batch val-6.0001-v3_1 --name val-480
출력: <root>/<batch>/<name>/pairs.jsonl, meta.json
"""

import argparse
import datetime as dt
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_COUNTS = {"ANSWERABLE": 168, "INSUFFICIENT_EVIDENCE": 168, "OPINION": 144}


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def assign_labels(eids: list[str], counts: dict[str, int], rng: random.Random) -> dict[str, str]:
    """청크 목록에 라벨을 하나씩 정해 준다. 강의별로 고르게 퍼지도록 강의 순서를 섞어 번갈아 고른다."""
    by_lec: dict[str, list[str]] = defaultdict(list)
    for e in eids:
        by_lec[e.rsplit("_", 1)[0]].append(e)
    for v in by_lec.values():
        rng.shuffle(v)
    # 강의를 돌아가며 한 청크씩 꺼내 청크 순서를 만든다(강의 비율 유지).
    total = sum(counts.values())
    order, lecs = [], sorted(by_lec)
    quota = {lec: round(total * len(by_lec[lec]) / len(eids)) for lec in lecs}
    while len(order) < total and any(by_lec.values()):
        for lec in lecs:
            if by_lec[lec] and quota[lec] > 0 and len(order) < total:
                order.append(by_lec[lec].pop())
                quota[lec] -= 1
        if all(q <= 0 or not by_lec[lec] for lec, q in quota.items()):
            for lec in lecs:  # 반올림으로 모자라면 남은 청크에서 채운다
                quota[lec] = 1
    labels = [lab for lab, n in counts.items() for _ in range(n)]
    rng.shuffle(labels)
    return dict(zip(order, labels))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("data/interim/synth"))
    ap.add_argument("--batch", required=True)
    ap.add_argument("--name", default="val-480")
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--counts", type=json.loads, default=DEFAULT_COUNTS, help='예: {"ANSWERABLE":168,...}')
    args = ap.parse_args()

    pairs = read_jsonl(args.root / args.batch / "pairs.jsonl")
    by_key = {(p["evidence_id"], p["label"]): p for p in pairs}
    eids = sorted({p["evidence_id"] for p in pairs})
    rng = random.Random(args.seed)
    picked_labels = assign_labels(eids, args.counts, rng)
    picked = [by_key[(e, lab)] for e, lab in sorted(picked_labels.items())]

    out = args.root / args.batch / args.name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "pairs.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for p in picked:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    meta = {
        "name": args.name,
        "created": dt.date.today().isoformat(),
        "from_batch": args.batch,
        "seed": args.seed,
        "counts": args.counts,
        "pairs": len(picked),
        "by_label": dict(Counter(p["label"] for p in picked)),
        "by_lecture": dict(sorted(Counter(p["lecture_id"] for p in picked).items())),
        "pair_ids": [p["pair_id"] for p in picked],
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(picked)}개 → {out / 'pairs.jsonl'}")
    print(json.dumps({k: meta[k] for k in ("by_label", "by_lecture")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
