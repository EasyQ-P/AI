"""흩어진 결과를 업로드용 train.jsonl · validation.jsonl로 합친다 (설계서 3.3.3, 7.4.2 등록 전 단계).

- train.jsonl: OCW 합성 쌍 + SQuAD 쌍을 3.3.3 학습 필드만 남겨 합친다.
  --ocw-counts를 주면 OCW를 라벨별 개수(예: 700/700/600)로 seed 추출한다. 강좌 비율은 섞어서 자연히 따른다.
  AI Hub 500은 --aihub(aihub_sample.py 결과)로 넣는다. AI Hub가 들어간 결과물도 AI Hub 데이터로 다룬다(3.1.3).
  --aihub 외 입력에 AI Hub 행이 있거나 검증셋에 AI Hub · SQuAD 행이 있으면 멈춘다.
- validation.jsonl: 검증 쌍(val-480)을 3.3.3 평가 필드의 질문 단위 행으로 바꾼다.
  candidates(검색 후보 20개) · gold_in_candidates는 검색 모듈이 나온 뒤 채운다(지금은 [] · null).
  gold_evidence_ids는 질문을 합성한 청크(답변 가능만)로 임시로 넣고, 후보가 정해지면 검수에서 고친다.
  label_source는 사람 전수 확인 전이라 LLM. 확인 후 LLM_HUMAN으로 바꾼다.
- 7.4.2 등록에는 test.jsonl, 평가용 교안 조각 파일, 검색 설정 버전(rc-vN)도 필요하다.

사용:
    uv run python scripts/data/build_splits.py --name ds-draft-1 \
        --ocw data/interim/synth/train-ocw-v3_1/pairs.jsonl \
        --squad data/interim/squad2/sample-500/pairs.jsonl \
        --val data/interim/synth/val-6.0001-v3_1/val-480/pairs.jsonl \
        --ocw-counts '{"ANSWERABLE":700,"INSUFFICIENT_EVIDENCE":700,"OPINION":600}'
출력: data/processed/<이름>/train.jsonl, validation.jsonl, meta.json
"""

import argparse
import datetime as dt
import json
import random
import sys
from collections import Counter
from pathlib import Path

TRAIN_FIELDS = [
    "pair_id", "course_id", "lecture_id", "question_text", "evidence_text", "evidence_type", "evidence_id",
    "page_no", "start_ms", "end_ms", "label", "target", "label_source", "source", "question_source",
    "gen_method", "is_hard_negative", "contains_aihub", "split", "dataset_version", "question_lang",
    "evidence_lang", "question_type", "has_english_term",
]


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def trim(pairs: list[dict], counts: dict[str, int], seed: int) -> list[dict]:
    """라벨별 counts개를 seed로 뽑는다. 원래 순서를 유지한다."""
    rng = random.Random(seed)
    keep = set()
    for lab, n in counts.items():
        ids = sorted(p["pair_id"] for p in pairs if p["label"] == lab)
        if len(ids) < n:
            raise ValueError(f"{lab}: {len(ids)}개뿐인데 {n}개를 뽑으려 함")
        keep.update(rng.sample(ids, n))
    return [p for p in pairs if p["pair_id"] in keep]


def to_train(p: dict) -> dict:
    missing = [f for f in TRAIN_FIELDS if f not in p]
    if missing:
        raise ValueError(f"{p.get('pair_id')}: 학습 필드 없음 {missing}")
    return {f: p[f] for f in TRAIN_FIELDS}


def to_eval(p: dict) -> dict:
    return {
        "eval_question_id": p["pair_id"],
        "course_id": p["course_id"],
        "lecture_id": p["lecture_id"],
        "question_text": p["question_text"],
        "candidates": [],
        "label": p["label"],
        "target": p["target"],
        "gold_evidence_ids": [p["evidence_id"]] if p["label"] == "ANSWERABLE" else [],
        "gold_in_candidates": None,
        "label_source": "LLM",
        "label_reviewer1": None,
        "label_reviewer2": None,
        "source": p["source"],
        "question_source": p["question_source"],
        "split": "VALIDATION",
        "dataset_version": None,
        "question_type": p.get("question_type"),
        # 검수용: 질문을 만든 청크(한국어 변환본)
        "synth_evidence_id": p["evidence_id"],
        "synth_evidence_text": p["evidence_text"],
    }


def check_aihub(ocw: list[dict], squad: list[dict], val: list[dict], aihub: list[dict]) -> None:
    """AI Hub 행은 --aihub로만 들어오고(contains_aihub true), 검증셋에는 AI Hub · SQuAD가 없어야 한다 (3.1.3, 3.3.4)."""
    if bad := [p.get("pair_id") for p in aihub if p.get("source") != "AIHUB" or p.get("contains_aihub") is not True]:
        raise ValueError(f"--aihub에 AI Hub가 아닌 행 {len(bad)}개(source AIHUB · contains_aihub true 필요)")
    if bad := [p.get("pair_id") for p in ocw + squad if p.get("source") == "AIHUB" or p.get("contains_aihub")]:
        raise ValueError(f"--ocw · --squad에 AI Hub 행 {len(bad)}개. AI Hub는 --aihub로만 넣는다")
    if bad := [p.get("pair_id") for p in val
               if p.get("source") in ("AIHUB", "SQUAD") or p.get("contains_aihub")]:
        raise ValueError(f"검증셋에 AI Hub · SQuAD 행 {len(bad)}개")


def build(
    ocw: list[dict], squad: list[dict], val: list[dict], ocw_counts: dict | None, seed: int,
    aihub: list[dict] | None = None,
):
    aihub = aihub or []
    check_aihub(ocw, squad, val, aihub)
    if ocw_counts:
        ocw = trim(ocw, ocw_counts, seed)
    train = [to_train(p) for p in ocw + squad + aihub]
    validation = [to_eval(p) for p in val]
    tc = {r["course_id"] for r in train} - {None}
    vc = {r["course_id"] for r in validation}
    if tc & vc:
        raise ValueError(f"같은 강좌가 학습 · 검증에 모두 있음: {sorted(tc & vc)}")
    if bad := sorted({r["split"] for r in train} - {"TRAIN"}):
        raise ValueError(f"학습셋에 TRAIN이 아닌 split이 있음: {bad}")
    meta = {
        "contains_aihub": bool(aihub),
        "train": {
            "rows": len(train),
            "by_label": dict(Counter(r["label"] for r in train)),
            "by_source": dict(Counter(r["source"] for r in train)),
            "by_course": dict(Counter(str(r["course_id"]) for r in train)),
        },
        "validation": {
            "rows": len(validation),
            "by_label": dict(Counter(r["label"] for r in validation)),
            "escalate": sum(r["target"] == 0 for r in validation),
        },
    }
    return train, validation, meta


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--out-root", type=Path, default=Path("data/processed"))
    ap.add_argument("--ocw", type=Path, required=True)
    ap.add_argument("--squad", type=Path, required=True)
    ap.add_argument("--val", type=Path, required=True)
    ap.add_argument("--aihub", type=Path, default=None, help="aihub_sample.py의 pairs.jsonl (학과 서버에서만)")
    ap.add_argument("--ocw-counts", type=json.loads, default=None)
    ap.add_argument("--seed", type=int, default=20261122)
    args = ap.parse_args()

    train, validation, meta = build(
        read_jsonl(args.ocw), read_jsonl(args.squad), read_jsonl(args.val), args.ocw_counts, args.seed,
        read_jsonl(args.aihub) if args.aihub else None,
    )
    out = args.out_root / args.name
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "train.jsonl", train)
    write_jsonl(out / "validation.jsonl", validation)
    meta = {
        "name": args.name,
        "created": dt.date.today().isoformat(),
        "inputs": {"ocw": str(args.ocw), "squad": str(args.squad), "val": str(args.val),
                   "aihub": str(args.aihub) if args.aihub else None},
        "ocw_counts": args.ocw_counts,
        "seed": args.seed,
        "pending": (["AI Hub 500(학과 서버)"] if not args.aihub else [])
        + ["validation candidates · gold_in_candidates(검색 모듈)",
           "validation 사람 전수 확인(label_source → LLM_HUMAN)", "test.jsonl", "평가용 교안 조각 파일",
           "hard negative"],
        **meta,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"train {len(train)}행 · validation {len(validation)}행 → {out}")
    if args.aihub:
        print("AI Hub 포함(contains_aihub): 이 train.jsonl도 AI Hub 데이터다. "
              "학과 서버 밖 · 외부 API · S3로 보내지 않는다.")
    print(json.dumps({k: meta[k] for k in ("train", "validation")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
