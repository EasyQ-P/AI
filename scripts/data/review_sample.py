"""학습셋 무작위 10% 사람 검수표를 만들고, 검수 결과로 라벨 오류율을 센다 (설계서 3.3.1 · 3.3.5).

- 대상: train.jsonl의 OCW 합성 쌍(label_source LLM, 어려운 오답 제외). SQuAD · AI Hub는 공개 라벨이라 제외.
- 뽑기: (근거 종류, 라벨)마다 --ratio(기본 10%)씩 seed로 뽑아 비율을 그대로 둔다. 같은 입력이면 같은 결과.
- 검수표: CSV(UTF-8 BOM, 엑셀 · 구글 시트에서 바로 열림). 사람이 '판정'(O/X)과 '맞는 라벨' · '메모'를 채운다.
  answer_hint(합성 때 LLM이 적은 근거 한 줄)는 --synth 배치의 pairs.jsonl에서 가져와 참고용으로 붙인다.
- add-hn: 학습셋에 붙은 어려운 오답(Sonnet 재확인 통과분)에서 n개(기본 50)를 근거 종류 비율대로 검수표 끝에
  덧붙인다. 재확인이 놓친 '실제로는 답이 있는' 오답 비율을 재기 위해.
- to-xlsx: review.csv → review.xlsx(사람이 채우는 파일). 줄바꿈 · 머리글 고정 · 판정 목록 · 안내 시트,
  교안(영어) 근거는 --translations로 참고 번역 열을 붙인다(판정은 원문 기준).
- summary: 채운 검수표(review.xlsx가 있으면 엑셀, 없으면 CSV) → 라벨 · 근거 종류별 오류율
  (합성 쌍과 어려운 오답 따로), X 목록. meta.json에 남긴다.
- fixes: 채운 검수표 → fixes.jsonl(O = 사람 확인, X + 맞는 라벨 = 라벨 수정, X + '제외' = 학습셋에서 뺌).
  build_splits.py --review-fixes로 학습셋에 반영한다(서버에서도 돌도록 표준 라이브러리 JSONL).

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


HN_HINT = "(어려운 오답) 검색이 고른 다른 조각. 이 근거로 답할 수 있으면 X"


def is_hard_negative_id(pair_id: str) -> bool:
    base, _, rank = pair_id.rpartition(":hn")
    return bool(base) and rank.isdigit()


def add_hard_negatives(train: list[dict], n: int, seed: int, out: Path) -> dict:
    """학습셋에 붙은 어려운 오답에서 n개를 근거 종류 비율대로 뽑아 검수표 끝에 덧붙인다.

    재확인(Sonnet)이 남긴 오답 중 실제로 답이 있는 쌍의 비율을 재기 위한 것. 이미 채운 판정은 건드리지 않는다.
    """
    csv_path = out / "review.csv"
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if any(is_hard_negative_id(r["pair_id"]) for r in rows):
        raise ValueError("검수표에 어려운 오답이 이미 있음")
    hns = [r for r in train if r.get("is_hard_negative") and is_hard_negative_id(r["pair_id"])]
    if any(r.get("contains_aihub") for r in hns):
        raise ValueError("AI Hub 행은 검수표(PC)로 꺼내지 않는다(3.1.3)")
    rng = random.Random(seed)
    by_type: dict[str, list[str]] = {}
    for r in hns:
        by_type.setdefault(r["evidence_type"], []).append(r["pair_id"])
    keep = set()
    for t in sorted(by_type):
        ids = sorted(by_type[t])
        keep.update(rng.sample(ids, min(len(ids), max(1, round(n * len(ids) / len(hns))))))
    picked = sorted((r for r in hns if r["pair_id"] in keep), key=lambda r: (r["evidence_type"], r["pair_id"]))
    with open(csv_path, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        for i, r in enumerate(picked, start=len(rows) + 1):
            w.writerow([i, r["pair_id"], r["evidence_type"], r["label"], r.get("question_type") or "",
                        r["question_text"], r["evidence_text"], HN_HINT, "", "", ""])
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["hard_negatives"] = {"added": dt.date.today().isoformat(), "rows": len(picked), "seed": seed,
                              "by_evidence_type": dict(Counter(r["evidence_type"] for r in picked))}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta["hard_negatives"]


XLSX_COLUMNS = [  # (머리글, CSV 열 또는 None, 너비)
    ("no", "no", 5), ("구분", None, 10), ("근거 종류", "evidence_type", 11), ("라벨", "label", 14),
    ("질문 유형", "question_type", 8), ("질문", "question_text", 30), ("근거(원문)", "evidence_text", 60),
    ("근거(참고 번역)", None, 60), ("참고(answer_hint)", "answer_hint", 28),
    ("판정(O/X)", "판정(O/X)", 9), ("맞는 라벨", "맞는 라벨", 18), ("메모", "메모", 24), ("pair_id", "pair_id", 18),
]
LABELS = ["ANSWERABLE", "INSUFFICIENT_EVIDENCE", "OPINION"]
DROP = "제외"  # 맞는 라벨에 고르면 학습셋에서 뺀다
GUIDE_LINES = [
    "학습셋 사람 검수표 (설계서 3.3.1 · 3.3.5). 노란 칸 3개(판정 · 맞는 라벨 · 메모)만 채운다.",
    "",
    "[판정] 근거 하나만 보고 이 질문의 라벨이 맞으면 O, 틀리면 X. X면 '맞는 라벨'을 고른다.",
    "  · ANSWERABLE: 근거에 답이 그대로 있거나, 근거 속 사실만으로 한 단계(문장 잇기 · 간단한 계산) 만에 답이 나온다.",
    "  · INSUFFICIENT_EVIDENCE: 같은 주제여도 답이 없다 / 일부만 답한다 / 상식 · 근거 밖 지식이 있어야 답한다.",
    "  · OPINION: 강연자 개인의 생각 · 평가 · 선호 · 추천을 묻는다(근거가 있어도).",
    "    원리 · 인과로 설명되는 '왜'는 의견 아님.",
    "  · 다른 쪽 · 다른 강의 · 강의 전체에 있는 답은 치지 않는다(이 근거 하나만).",
    "",
    "[구분] 합성 = OCW 합성 쌍 10% 표본(라벨 오류율). 어려운 오답 = 검색이 고른 다른 조각에 붙인 근거 부족 쌍",
    "  (Sonnet 재확인 통과분). 어려운 오답은 '이 근거로 답할 수 있으면 X'.",
    "[근거(참고 번역)] 교안(영어 원문)만 있다. 판정은 원문 기준, 번역은 읽기 도움용(LLM 번역, 틀릴 수 있음).",
    "[참고(answer_hint)] 질문을 합성할 때 LLM이 적은 근거 한 줄. 맞는지는 직접 확인한다.",
    "",
    "예) 질문 '안정 정렬이 무슨 뜻이에요?' + 근거 'Want sort to be stable: repeated keys appear in output",
    "    in same order as input' → 라벨 ANSWERABLE이면 판정 O.",
    "",
    "다 채우면: uv run python scripts/data/review_sample.py summary --name <이름>  (엑셀을 읽어 오류율을 센다)",
]


def read_review(out: Path) -> list[dict]:
    """검수 결과 읽기. review.xlsx가 있으면 엑셀(사람이 채운 쪽), 없으면 review.csv."""
    xlsx = out / "review.xlsx"
    if xlsx.exists():
        from openpyxl import load_workbook

        ws = load_workbook(xlsx, read_only=True)["검수"]
        it = ws.iter_rows(values_only=True)
        head = list(next(it))
        rows = []
        for vals in it:
            cells = dict(zip(head, vals, strict=False))
            if not cells.get("pair_id"):
                continue
            rows.append({col: ("" if cells.get(h) is None else str(cells.get(h)))
                         for h, col, _ in XLSX_COLUMNS if col})
        return rows
    with open(out / "review.csv", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def to_xlsx(out: Path, translations: dict[str, str]) -> Path:
    """review.csv → review.xlsx(줄바꿈 · 칸 너비 · 머리글 고정 · 판정 목록 · 진행 현황). 이미 있으면 멈춘다."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    path = out / "review.xlsx"
    if path.exists():
        raise ValueError(f"{path}가 이미 있음(채운 판정 덮어쓰기 방지)")
    with open(out / "review.csv", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    font, bold = Font(name="맑은 고딕", size=10), Font(name="맑은 고딕", size=10, bold=True)
    fill_in = PatternFill("solid", fgColor="FFF2CC")
    fill_hn = PatternFill("solid", fgColor="EDEDED")
    head_fill = PatternFill("solid", fgColor="D9E1F2")
    wrap = Alignment(wrap_text=True, vertical="top")

    wb = Workbook()
    ws = wb.active
    ws.title = "검수"
    ws.append([h for h, _, _ in XLSX_COLUMNS])
    for c, (_, _, width) in enumerate(XLSX_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c)
        cell.font, cell.fill, cell.alignment = bold, head_fill, Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[cell.column_letter].width = width
    input_cols = {i for i, (h, _, _) in enumerate(XLSX_COLUMNS, start=1) if h in ("판정(O/X)", "맞는 라벨", "메모")}
    for r in rows:
        hn = is_hard_negative_id(r["pair_id"])
        vals = []
        for h, col, _ in XLSX_COLUMNS:
            if h == "구분":
                vals.append("어려운 오답" if hn else "합성")
            elif h == "근거(참고 번역)":
                vals.append(translations.get(r["pair_id"], ""))
            elif h == "no":
                vals.append(int(r["no"]))
            else:
                vals.append(r[col])
        ws.append(vals)
        for c in range(1, len(XLSX_COLUMNS) + 1):
            cell = ws.cell(row=ws.max_row, column=c)
            cell.font, cell.alignment = font, wrap
            if c in input_cols:
                cell.fill = fill_in
            elif hn:
                cell.fill = fill_hn
    last = ws.max_row
    col_of = {h: ws.cell(row=1, column=i).column_letter for i, (h, _, _) in enumerate(XLSX_COLUMNS, start=1)}
    ox = DataValidation(type="list", formula1='"O,X"', allow_blank=True)
    lab = DataValidation(type="list", formula1='"' + ",".join([*LABELS, DROP]) + '"', allow_blank=True)
    ws.add_data_validation(ox)
    ws.add_data_validation(lab)
    ox.add(f"{col_of['판정(O/X)']}2:{col_of['판정(O/X)']}{last}")
    lab.add(f"{col_of['맞는 라벨']}2:{col_of['맞는 라벨']}{last}")
    ws.freeze_panes = "G2"
    ws.auto_filter.ref = f"A1:{col_of['pair_id']}{last}"

    g = wb.create_sheet("안내", 0)
    g.column_dimensions["A"].width = 24
    g.column_dimensions["B"].width = 14
    g.column_dimensions["C"].width = 14
    g.column_dimensions["D"].width = 14
    for i, line in enumerate(GUIDE_LINES, start=1):
        g.cell(row=i, column=1, value=line).font = bold if i == 1 else font
    base = len(GUIDE_LINES) + 2
    g.cell(row=base, column=1, value="진행 현황").font = bold
    for c, h in enumerate(["", "전체", "판정함", "X"], start=1):
        g.cell(row=base + 1, column=c, value=h or None).font = bold
    k, j = col_of["구분"], col_of["판정(O/X)"]
    for i, kind in enumerate(["합성", "어려운 오답"], start=base + 2):
        rng_k, rng_j = f"검수!${k}$2:${k}${last}", f"검수!${j}$2:${j}${last}"
        g.cell(row=i, column=1, value=kind).font = font
        g.cell(row=i, column=2, value=f'=COUNTIF({rng_k},"{kind}")').font = font
        g.cell(row=i, column=3, value=f'=COUNTIFS({rng_k},"{kind}",{rng_j},"O")+COUNTIFS({rng_k},"{kind}",{rng_j},"X")'
               ).font = font
        g.cell(row=i, column=4, value=f'=COUNTIFS({rng_k},"{kind}",{rng_j},"X")').font = font
    g.cell(row=base + 4, column=1, value="오류율 = X ÷ 판정함 (summary가 정식으로 계산)").font = font
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)
    return path


def fixes(out: Path) -> list[dict]:
    """채운 검수표 → 학습셋에 반영할 목록 {pair_id, action(ok/relabel/drop), label}.

    O → ok(사람 확인), X + 맞는 라벨 → relabel, X + '제외' → drop. 판정 안 한 행은 넣지 않는다.
    X인데 맞는 라벨이 비었거나 원래 라벨과 같으면 오류(검수표를 먼저 고친다).
    """
    out_rows, bad = [], []
    for r in read_review(out):
        j = r["판정(O/X)"].strip().upper()
        if j == "O":
            out_rows.append({"pair_id": r["pair_id"], "action": "ok", "label": r["label"]})
        elif j == "X":
            c = r["맞는 라벨"].strip()
            if c == DROP:
                out_rows.append({"pair_id": r["pair_id"], "action": "drop", "label": None})
            elif c in LABELS and c != r["label"]:
                out_rows.append({"pair_id": r["pair_id"], "action": "relabel", "label": c})
            else:
                bad.append(f"{r['no']}행 {r['pair_id']}: X인데 맞는 라벨이 '{c}'")
    if bad:
        raise ValueError("검수표 확인 필요:\n" + "\n".join(bad))
    return out_rows


def summary(out: Path) -> dict:
    rows = read_review(out)
    judged_all = [r for r in rows if r["판정(O/X)"].strip().upper() in ("O", "X")]
    # 합성 쌍 10% 검수와 어려운 오답 검수는 따로 센다(목적이 다름).
    judged = [r for r in judged_all if not is_hard_negative_id(r["pair_id"])]
    judged_hn = [r for r in judged_all if is_hard_negative_id(r["pair_id"])]
    wrong = [r for r in judged_all if r["판정(O/X)"].strip().upper() == "X"]

    def rate(rs: list[dict]) -> dict:
        x = sum(r["판정(O/X)"].strip().upper() == "X" for r in rs)
        return {"n": len(rs), "x": x, "error_rate": round(x / len(rs), 3) if rs else None}

    result = {
        "rows": len(rows),
        "judged": len(judged_all),
        "overall": rate(judged),
        "by_label": {lab: rate([r for r in judged if r["label"] == lab])
                     for lab in sorted({r["label"] for r in judged})},
        "by_evidence_type": {t: rate([r for r in judged if r["evidence_type"] == t])
                             for t in sorted({r["evidence_type"] for r in judged})},
        "hard_negatives": {"overall": rate(judged_hn),
                           "by_evidence_type": {t: rate([r for r in judged_hn if r["evidence_type"] == t])
                                                for t in sorted({r["evidence_type"] for r in judged_hn})}},
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
    h = sub.add_parser("add-hn", help="학습셋의 어려운 오답 n개를 검수표 끝에 덧붙인다")
    h.add_argument("--train", type=Path, required=True)
    h.add_argument("--name", required=True)
    h.add_argument("--n", type=int, default=50)
    h.add_argument("--seed", type=int, default=20261126)
    x = sub.add_parser("to-xlsx", help="review.csv → review.xlsx(사람이 채우는 파일)")
    x.add_argument("--name", required=True)
    x.add_argument("--translations", type=Path, default=None, help="참고 번역 JSONL {pair_id, ko}")
    s = sub.add_parser("summary")
    s.add_argument("--name", required=True)
    f = sub.add_parser("fixes", help="채운 검수표 → fixes.jsonl(build_splits.py --review-fixes용)")
    f.add_argument("--name", required=True)
    args = ap.parse_args()
    out = args.root / args.name
    if args.cmd == "make":
        meta = make(read_jsonl(args.train), args.synth, args.ratio, args.seed, out)
        print(f"검수표 {meta['rows']}행 → {out / 'review.csv'}")
        print(json.dumps(meta["by_type_label"], ensure_ascii=False, indent=2))
    elif args.cmd == "to-xlsx":
        tr = {r["pair_id"]: r["ko"] for r in read_jsonl(args.translations)} if args.translations else {}
        print(f"엑셀 검수표 → {to_xlsx(out, tr)} (참고 번역 {len(tr)}행)")
    elif args.cmd == "fixes":
        rows = fixes(out)
        with open(out / "fixes.jsonl", "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"수정 목록 {len(rows)}행 → {out / 'fixes.jsonl'}")
        print(json.dumps(dict(Counter(r["action"] for r in rows)), ensure_ascii=False))
    elif args.cmd == "add-hn":
        info = add_hard_negatives(read_jsonl(args.train), args.n, args.seed, out)
        print(f"어려운 오답 {info['rows']}행 추가 → {out / 'review.csv'}")
        print(json.dumps(info["by_evidence_type"], ensure_ascii=False))
    else:
        print(json.dumps(summary(out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
