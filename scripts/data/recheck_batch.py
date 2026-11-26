"""어려운 오답 Sonnet 재확인 배치 준비 · 검증 (설계서 3.3.4 학습셋 5단계: "이 근거로 답할 수 있나").

LLM 호출은 스크립트 밖에서 한다(Sonnet 하위 에이전트가 parts/in_NN.jsonl → parts/out_NN.jsonl).
  prepare: 학습셋에 실제로 쓸 오답만 고른다. 답변 가능 질문마다 '아직 확인 안 한' 오답을 순위대로,
           통과(answerable=false)한 개수가 --hn-max가 되도록 모자란 만큼만. --checked로 이전 결과를 주면
           빠진 자리를 다음 순위로 채우는 보충 배치가 된다.
  ingest:  출력을 검사해 result.jsonl {pair_id, answerable, reason}로 모은다.
           build_splits.py --hn-recheck에 이 파일(들)을 준다.

배치 폴더: data/interim/recheck/<이름>/  input.jsonl, parts/, TASK.md, result.jsonl, meta.json

사용:
    uv run python scripts/data/recheck_batch.py prepare --name hn-recheck-1 \
        --train data/processed/ds-draft-2/train.jsonl \
        --hard-negatives data/easyq_search_rc-v1/hard_negatives.jsonl --hn-max 2 --part-size 150
    uv run python scripts/data/recheck_batch.py ingest --name hn-recheck-1 --model claude-sonnet-5-5
    # 빠진 자리 보충
    uv run python scripts/data/recheck_batch.py prepare --name hn-recheck-2 ... \
        --checked data/interim/recheck/hn-recheck-1/result.jsonl
"""

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

PROMPT = "hn_recheck_v1"
TASK = """# 묶음 작업 지시 ({name}, 어려운 오답 재확인)
parts/in_NN.jsonl의 각 줄(질문 하나 + 근거 하나)마다 출력 한 줄을 parts/out_NN.jsonl에 쓴다
(입력과 같은 순서, 줄 수 같게).

scripts/data/prompts/{prompt}.md 기준으로 "이 근거만 보고 이 질문에 답할 수 있나"를 판단한다.
출력 한 줄(JSON, ensure_ascii=False): {{"pair_id": "...", "answerable": false, "reason": "..."}}

규칙: 줄마다 직접 읽고 판단한다(키워드 겹침 같은 규칙 코드로 판정하지 않는다). 다른 모델을 부르지 않는다.
파일 쓰기는 Python json.dumps(ensure_ascii=False). 끝나면 줄 수 · JSON 파싱 · pair_id 순서를 확인한다.
"""


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def split_hn_id(pair_id: str) -> tuple[str, int]:
    base, _, rank = pair_id.rpartition(":hn")
    if not base or not rank.isdigit():
        raise ValueError(f"어려운 오답 pair_id 형식이 아님(<원 ID>:hnN): {pair_id}")
    return base, int(rank)


def select(train: list[dict], hard_negatives: list[dict], hn_max: int, checked: dict[str, bool]) -> list[dict]:
    """질문마다 통과 개수가 hn_max가 되도록, 확인 안 한 오답을 순위대로 모자란 만큼 고른다."""
    if any(r.get("contains_aihub") for r in train + hard_negatives):
        raise ValueError("AI Hub 행은 재확인(외부 모델)에 넣을 수 없다(3.1.3)")
    targets = {r["pair_id"] for r in train if r["source"] == "MIT_OCW" and r["label"] == "ANSWERABLE"
               and not r.get("is_hard_negative")}
    by_base: dict[str, list[tuple[int, dict]]] = {}
    for h in hard_negatives:
        base, rank = split_hn_id(h["pair_id"])
        if base in targets:
            by_base.setdefault(base, []).append((rank, h))
    picked = []
    for base in sorted(by_base):
        ranked = sorted(by_base[base], key=lambda x: x[0])
        passed = sum(1 for _, h in ranked if checked.get(h["pair_id"]) is False)
        need = hn_max - passed
        for _, h in ranked:
            if need <= 0:
                break
            if h["pair_id"] not in checked:
                picked.append(h)
                need -= 1
    return picked


def cmd_prepare(args) -> None:
    checked = {}
    for f in args.checked or []:
        checked.update({r["pair_id"]: bool(r["answerable"]) for r in read_jsonl(f)})
    hns = [h for f in args.hard_negatives for h in read_jsonl(f)]
    picked = select(read_jsonl(args.train), hns, args.hn_max, checked)
    out = args.root / args.name
    if (out / "input.jsonl").exists():
        sys.exit(f"{out}가 이미 있음. --name을 바꾸세요")
    rows = [{"pair_id": h["pair_id"], "evidence_type": h["evidence_type"], "question_text": h["question_text"],
             "evidence_text": h["evidence_text"]} for h in picked]
    write_jsonl(out / "input.jsonl", rows)
    for i in range(0, len(rows), args.part_size):
        write_jsonl(out / "parts" / f"in_{i // args.part_size + 1:02d}.jsonl", rows[i : i + args.part_size])
    (out / "TASK.md").write_text(TASK.format(name=args.name, prompt=PROMPT), encoding="utf-8")
    meta = {
        "name": args.name, "created": dt.date.today().isoformat(), "prompt": PROMPT, "hn_max": args.hn_max,
        "inputs": {"train": str(args.train), "hard_negatives": [str(f) for f in args.hard_negatives],
                   "checked": [str(f) for f in args.checked or []]},
        "rows": len(rows), "parts": -(-len(rows) // args.part_size) if rows else 0,
        "by_evidence_type": dict(Counter(r["evidence_type"] for r in rows)), "model": None,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"재확인 {len(rows)}건 · 묶음 {meta['parts']}개 → {out}")
    print(json.dumps(meta["by_evidence_type"], ensure_ascii=False))


def validate(inputs: list[dict], outputs: list[dict]) -> tuple[list[dict], dict]:
    want = {r["pair_id"]: r for r in inputs}
    errors, seen, result = {}, set(), []
    for o in outputs:
        pid = o.get("pair_id")
        if pid not in want:
            errors[str(pid)] = "입력에 없는 pair_id"
        elif pid in seen:
            errors[pid] = "중복"
        elif not isinstance(o.get("answerable"), bool):
            errors[pid] = "answerable이 true/false가 아님"
        else:
            seen.add(pid)
            result.append({"pair_id": pid, "answerable": o["answerable"], "reason": str(o.get("reason", ""))})
    missing = [p for p in want if p not in seen and p not in errors]
    return result, {"errors": errors, "missing": missing}


def cmd_ingest(args) -> None:
    out = args.root / args.name
    inputs = read_jsonl(out / "input.jsonl")
    outputs = [o for f in sorted((out / "parts").glob("out_*.jsonl")) for o in read_jsonl(f)]
    result, problems = validate(inputs, outputs)
    write_jsonl(out / "result.jsonl", result)
    etype = {r["pair_id"]: r["evidence_type"] for r in inputs}
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    meta.update({
        "model": args.model, "checked": dt.date.today().isoformat(), "results": len(result),
        "answerable": sum(r["answerable"] for r in result),
        "answerable_by_evidence_type": dict(Counter(etype[r["pair_id"]] for r in result if r["answerable"])),
        **problems,
    })
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 {len(result)}/{len(inputs)} · 답할 수 있음(뺌) {meta['answerable']} · "
          f"누락 {len(problems['missing'])} · 오류 {len(problems['errors'])}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("data/interim/recheck"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--name", required=True)
    p.add_argument("--train", type=Path, required=True)
    p.add_argument("--hard-negatives", type=Path, nargs="+", required=True)
    p.add_argument("--hn-max", type=int, default=2)
    p.add_argument("--checked", type=Path, nargs="*", default=None, help="이전 재확인 result.jsonl(보충 배치)")
    p.add_argument("--part-size", type=int, default=150)
    i = sub.add_parser("ingest")
    i.add_argument("--name", required=True)
    i.add_argument("--model", required=True)
    args = ap.parse_args()
    {"prepare": cmd_prepare, "ingest": cmd_ingest}[args.cmd](args)


if __name__ == "__main__":
    main()
