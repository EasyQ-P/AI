"""흩어진 결과를 업로드용 train.jsonl · validation.jsonl로 합친다 (설계서 3.3.3, 7.4.2 등록 전 단계).

- train.jsonl: OCW 합성 쌍 + SQuAD 쌍을 3.3.3 학습 필드만 남겨 합친다.
  --ocw-counts를 주면 OCW를 라벨별 개수(예: 700/700/600)로 seed 추출한다. 강좌 비율은 섞어서 자연히 따른다.
  B안(2026-11-25): --ocw에 발화 쌍 · 교안 쌍 파일을 함께 주고 --ocw-counts를 근거 종류별로 준다.
    예: '{"TRANSCRIPT":{"ANSWERABLE":550,"INSUFFICIENT_EVIDENCE":550,"OPINION":450},
          "DOCUMENT":{"ANSWERABLE":150,"INSUFFICIENT_EVIDENCE":150,"OPINION":150}}'
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

학과 서버(Python 3.9)에서 --aihub로 합칠 수 있게 표준 라이브러리만 쓰고 3.9에서 도는 문법만 쓴다.
"""

from __future__ import annotations

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


def trim(pairs: list[dict], counts: dict, seed: int) -> list[dict]:
    """라벨별 counts개를 seed로 뽑는다. 원래 순서를 유지한다.

    counts는 {라벨: 개수} 또는 근거 종류별 {"TRANSCRIPT": {라벨: 개수}, "DOCUMENT": {라벨: 개수}} (B안, 2026-11-25).
    {라벨: 개수}는 예전과 같은 결과를 낸다(ds-draft-1 재현).
    """
    rng = random.Random(seed)
    nested = all(isinstance(v, dict) for v in counts.values())
    groups = counts.items() if nested else [(None, counts)]
    keep = set()
    for etype, by_label in groups:
        for lab, n in by_label.items():
            ids = sorted(p["pair_id"] for p in pairs
                         if p["label"] == lab and (etype is None or p["evidence_type"] == etype))
            if len(ids) < n:
                raise ValueError(f"{etype or ''} {lab}: {len(ids)}개뿐인데 {n}개를 뽑으려 함".strip())
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


def base_pair_id(hn_pair_id: str) -> tuple[str, int]:
    """'<원 쌍 ID>:hn3' → ('<원 쌍 ID>', 3)"""
    base, _, rank = hn_pair_id.rpartition(":hn")
    if not base or not rank.isdigit():
        raise ValueError(f"어려운 오답 pair_id 형식이 아님(<원 ID>:hnN): {hn_pair_id}")
    return base, int(rank)


def attach_hard_negatives(
    ocw: list[dict], hard_negatives: list[dict], max_per_question: int, checked: dict[str, bool] | None,
) -> tuple[list[dict], dict]:
    """고른 OCW 답변 가능 쌍에 어려운 오답을 질문당 max_per_question개까지 순위대로 붙인다 (3.3.4 5단계).

    checked: Sonnet 재확인 결과 {pair_id: answerable}. 주면 재확인을 통과한(answerable=false) 오답만 쓰고,
    답할 수 있음(true)과 아직 확인 안 한 오답은 뺀다. None이면 재확인 전(메타에 표시).
    label_source는 생성 의도 라벨이라 LLM으로 둔다.
    """
    targets = {p["pair_id"] for p in ocw if p["label"] == "ANSWERABLE"}
    by_base: dict[str, list[tuple[int, dict]]] = {}
    for h in hard_negatives:
        if h.get("label") != "INSUFFICIENT_EVIDENCE" or not h.get("is_hard_negative"):
            raise ValueError(f"어려운 오답이 아닌 행: {h.get('pair_id')}")
        base, rank = base_pair_id(h["pair_id"])
        if base in targets:
            by_base.setdefault(base, []).append((rank, h))
    out, dropped, unchecked, counts = [], 0, 0, Counter()
    for base in sorted(targets):
        picked = []
        for _, h in sorted(by_base.get(base, []), key=lambda x: x[0]):
            if checked is not None:
                if h["pair_id"] not in checked:
                    unchecked += 1
                    continue
                if checked[h["pair_id"]]:
                    dropped += 1
                    continue
            if len(picked) < max_per_question:
                picked.append({**h, "label_source": "LLM", "split": "TRAIN"})
        counts[len(picked)] += 1
        out += picked
    stats = {
        "attached": len(out),
        "per_question": {str(k): v for k, v in sorted(counts.items())},
        "dropped_recheck_answerable": dropped,
        "skipped_unchecked": unchecked,
        "rechecked": checked is not None,
        "by_evidence_type": dict(Counter(h["evidence_type"] for h in out)),
    }
    return out, stats


def evidence_by_label(rows: list[dict]) -> dict:
    """라벨별 근거 종류 비율 · 길이(단어 수 중앙값). 근거 종류나 길이로 라벨이 드러나는지 확인용."""
    out = {}
    for lab in sorted({r["label"] for r in rows}):
        rs = [r for r in rows if r["label"] == lab]
        by_type = {}
        for t in sorted({r["evidence_type"] for r in rs}):
            ws = sorted(len(r["evidence_text"].split()) for r in rs if r["evidence_type"] == t)
            by_type[t] = {"n": len(ws), "words_median": ws[len(ws) // 2]}
        doc_ratio = round(sum(r["evidence_type"] == "DOCUMENT" for r in rs) / len(rs), 3)
        out[lab] = {"n": len(rs), "document_ratio": doc_ratio, "by_evidence_type": by_type}
    return out


def build(
    ocw: list[dict], squad: list[dict], val: list[dict], ocw_counts: dict | None, seed: int,
    aihub: list[dict] | None = None, hard_negatives: list[dict] | None = None, hn_max: int = 2,
    hn_checked: dict[str, bool] | None = None,
):
    aihub = aihub or []
    check_aihub(ocw, squad, val, aihub)
    if ocw_counts:
        ocw = trim(ocw, ocw_counts, seed)
    hn_rows, hn_stats = attach_hard_negatives(ocw, hard_negatives, hn_max, hn_checked) if hard_negatives else (
        [], None)
    train = [to_train(p) for p in ocw + hn_rows + squad + aihub]
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
            "by_evidence_type_label": {f"{t}/{lab}": n for (t, lab), n in
                                       sorted(Counter((r["evidence_type"], r["label"]) for r in train).items())},
            "by_course": dict(Counter(str(r["course_id"]) for r in train)),
            "hard_negatives": hn_stats,
            "ocw_evidence_by_label": evidence_by_label([r for r in train if r["source"] == "MIT_OCW"]),
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
    ap.add_argument("--ocw", type=Path, nargs="+", required=True,
                    help="OCW 합성 쌍 파일(발화 · 교안 여러 개 가능)")
    ap.add_argument("--squad", type=Path, required=True)
    ap.add_argument("--val", type=Path, required=True)
    ap.add_argument("--aihub", type=Path, default=None, help="aihub_sample.py의 pairs.jsonl (학과 서버에서만)")
    ap.add_argument("--ocw-counts", type=json.loads, default=None)
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--hard-negatives", type=Path, nargs="*", default=None,
                    help="scripts/search/hard_negatives.py의 hard_negatives.jsonl(여러 개 가능)")
    ap.add_argument("--hn-max", type=int, default=2, help="질문당 어려운 오답 최대 개수(설계 기본 2)")
    ap.add_argument("--hn-recheck", type=Path, nargs="*", default=None,
                    help="recheck_batch.py의 result.jsonl(여러 개 가능). 통과한(answerable=false) 오답만 쓴다")
    args = ap.parse_args()

    hard_negatives = [p for f in args.hard_negatives for p in read_jsonl(f)] if args.hard_negatives else None
    hn_checked = ({r["pair_id"]: bool(r["answerable"]) for f in args.hn_recheck for r in read_jsonl(f)}
                  if args.hn_recheck else None)
    train, validation, meta = build(
        [p for f in args.ocw for p in read_jsonl(f)], read_jsonl(args.squad), read_jsonl(args.val),
        args.ocw_counts, args.seed, read_jsonl(args.aihub) if args.aihub else None,
        hard_negatives, args.hn_max, hn_checked,
    )
    out = args.out_root / args.name
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "train.jsonl", train)
    write_jsonl(out / "validation.jsonl", validation)
    meta = {
        "name": args.name,
        "created": dt.date.today().isoformat(),
        "inputs": {"ocw": [str(f) for f in args.ocw],"squad": str(args.squad), "val": str(args.val),
                   "aihub": str(args.aihub) if args.aihub else None,
                   "hard_negatives": [str(f) for f in args.hard_negatives] if args.hard_negatives else None,
                   "hn_recheck": [str(f) for f in args.hn_recheck] if args.hn_recheck else None},
        "ocw_counts": args.ocw_counts,
        "hn_max": args.hn_max if args.hard_negatives else None,
        "seed": args.seed,
        "pending": (["AI Hub 500(학과 서버)"] if not args.aihub else [])
        + ["validation candidates · gold_in_candidates(검색 모듈)",
           "validation 사람 전수 확인(label_source → LLM_HUMAN)", "test.jsonl", "평가용 교안 조각 파일"]
        + ([] if args.hard_negatives else ["hard negative"])
        + (["hard negative Sonnet 재확인"] if args.hard_negatives and not args.hn_recheck else []),
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
