"""LLM 합성 배치 준비 · 검증 (설계서 3.2.2 (1) 4단계 한국어 변환, 3.3.4 학습셋 3 · 4단계 질문 합성 · 1차 라벨).

LLM 호출은 이 스크립트 밖에서 한다(Sonnet). 이 스크립트는
  prepare: 청크를 골라 배치 입력(input.jsonl)과 메타(meta.json)를 만들고
  ingest:  LLM 출력(output.jsonl)을 검사해 3.3.3 필드의 학습 쌍(pairs.jsonl)으로 바꾼다.

배치 폴더: data/interim/synth/<batch_id>/  (커밋 금지)
  input.jsonl   evidence_id, lecture_id, course_id, evidence_text(영어 원문)
  output.jsonl  LLM 출력: evidence_id, ko_text, content, skip,
                questions[gen_method, question_text, question_type, answer_hint]
  pairs.jsonl   학습 쌍(3.3.3)
  meta.json     모델 ID, 날짜, 프롬프트 버전, 원본 청크 ID, 제외 개수

사용:
    uv run python scripts/data/synth_batch.py prepare --batch trial-6.006-v1 --course 6.006_S20 --n 30
    uv run python scripts/data/synth_batch.py ingest --batch trial-6.006-v1 --model <모델 ID>
    # 고른 강의의 청크 전부(회의안건 B3), 50청크씩 묶음 파일(parts/in_NN.jsonl)도 만든다
    uv run python scripts/data/synth_batch.py prepare --batch train-ocw-v3_1 \
        --lectures 6.006_S20_L07 6.006_S20_L13 --question-prompt question_synth_v3_1 --part-size 50
"""

import argparse
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_PROMPTS = {"rewrite": "ko_rewrite_v1", "questions": "question_synth_v3_1"}
SPLIT_OF = {"6.006_S20": "TRAIN", "6.046J_S15": "TRAIN", "6.034_F10": "TRAIN", "6.0001_F16": "VALIDATION"}

LABEL_OF = {"ANSWERABLE": "ANSWERABLE", "OUT_OF_SCOPE": "INSUFFICIENT_EVIDENCE", "OPINION": "OPINION"}
QUESTION_TYPES = {"개념", "방법", "이유", "비교", "예시", "운영", "의견"}
# 청크마다 돌아가며 목표 유형을 정해 특정 유형 쏠림을 막는다(question_synth_v2, 3.2.4 질문 유형).
# 운영은 수업 안내가 있는 청크에만 따로 준다(assign_target_types).
TOPIC_TYPES = ["개념", "방법", "이유", "비교", "예시"]
LOGISTICS_RE = re.compile(
    r"\b(homework|problem sets?|psets?|exams?|quiz(?:zes)?|midterms?|recitations?|office hours|piazza|"
    r"deadline|grading|syllabus|lecture notes|textbook|course staff|TAs?|"
    r"(?:next|last) (?:lecture|week|class))\b",
    re.IGNORECASE,
)
# 'last time', 'next time (through the loop)', 'grade(s)'는 뺐다.
# 복습 말투 · 반복문 · 변수 이름(grades)을 수업 안내로 잘못 잡았다(measure-6.0001-v2 점검).
# 의견 질문에 몰리는 말투 단서(보세요 · 생각하세요 · 교수님 · 추천 · 낫 · 좋아 · 괜찮). 라벨별 비율을 점검한다.
OPINION_CUE_RE = re.compile(r"(보세요|생각하세요|교수님|추천|낫|나아|나은|좋아|좋을까|괜찮)")
# 단어 겹침 확인선(v3 30청크 시험 평균: 답변 가능 0.54, 근거 부족 0.38 → v3_1에서 차이를 줄이는 것이 목표)
ANS_MAX_OVERLAP = 0.65
OOS_MIN_OVERLAP = 0.20
QUESTION_LEN = (15, 35)
HANGUL_RE = re.compile(r"[가-힣]")
ALPHA_RE = re.compile(r"[A-Za-z]")


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def select_chunks(chunks: list[dict], n: int, seed: int, exclude_lectures: set[str]) -> list[dict]:
    """강의(L) 청크 중 제외 강의를 빼고 seed로 n개를 고른다. 같은 입력이면 같은 결과."""
    pool = [
        c
        for c in chunks
        if c["lecture_id"].rsplit("_", 1)[-1].startswith("L") and c["lecture_id"] not in exclude_lectures
    ]
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    return sorted(picked, key=lambda c: c["evidence_id"])


def lecture_chunks(chunks_dir: Path, lectures: list[str]) -> list[dict]:
    """고른 강의의 청크 전부(회의안건 B3: 강의 단위로 고르고 고른 강의는 전부 변환). 강좌가 여럿이어도 된다."""
    want = set(lectures)
    courses = sorted({lid.rsplit("_", 1)[0] for lid in want})
    picked = [c for course in courses for c in read_jsonl(chunks_dir / f"{course}.jsonl") if c["lecture_id"] in want]
    if missing := want - {c["lecture_id"] for c in picked}:
        sys.exit(f"청크가 없는 강의: {sorted(missing)}")
    return sorted(picked, key=lambda c: c["evidence_id"])


def has_logistics(text: str) -> bool:
    """영어 원문 청크에 수업 운영(과제 · 시험 · 진행 안내) 이야기가 있는지."""
    return bool(LOGISTICS_RE.search(text))


def assign_target_types(texts: list[str], seed: int) -> list[dict]:
    """청크마다 ANSWERABLE · OUT_OF_SCOPE 목표 유형을 고르게 배정한다(같은 seed면 같은 결과).

    운영 유형은 수업 안내가 있는 청크에만 주고, 그 청크들 안에서 답변 가능과 근거 부족에 번갈아 준다.
    강의 내용만 있는 청크에 운영을 주면 '운영 질문 = 근거 부족' 지름길이 생기기 때문이다(trial-6.006-v2 점검).
    """
    rng = random.Random(seed + 1)
    k = len(TOPIC_TYPES)
    order = [i % k for i in range(len(texts))]
    rng.shuffle(order)
    targets, ops = [], 0
    for text, i in zip(texts, order, strict=True):
        # 근거 부족 질문은 같은 청크의 답변 가능 질문과 다른 유형이 되도록 밀어 둔다.
        ans, oos = TOPIC_TYPES[i], TOPIC_TYPES[(i + k // 2) % k]
        if has_logistics(text):
            if ops % 2 == 0:
                ans = "운영"
            else:
                oos = "운영"
            ops += 1
        targets.append({"ANSWERABLE": ans, "OUT_OF_SCOPE": oos, "OPINION": "의견"})
    return targets


def tokens(text: str) -> set[str]:
    """겹침 계산용 단어 집합. 한국어는 조사가 붙으므로 어절의 앞 두 글자, 영어는 소문자 단어."""
    out = set()
    for w in re.findall(r"[가-힣]+|[A-Za-z][A-Za-z0-9_]*", text):
        out.add(w.lower() if ALPHA_RE.match(w) else w[:2])
    return out


def overlap(question: str, evidence: str) -> float:
    q = tokens(question)
    return len(q & tokens(evidence)) / len(q) if q else 0.0


def overlap_warnings(pairs: list[dict]) -> dict:
    """질문-근거 단어 겹침이 라벨 지름길이 될 만한 쌍(question_synth_v3_1 규칙). 오류는 아니고 확인용 목록이다.

    답변 가능 질문이 청크 말을 너무 많이 쓰거나(ANS_MAX_OVERLAP 초과),
    근거 부족 질문이 청크 말을 거의 안 쓰면(OOS_MIN_OVERLAP 미만) 겹침만으로 라벨이 드러난다.
    """
    too_high = [
        p["pair_id"]
        for p in pairs
        if p["gen_method"] == "ANSWERABLE" and overlap(p["question_text"], p["evidence_text"]) > ANS_MAX_OVERLAP
    ]
    too_low = [
        p["pair_id"]
        for p in pairs
        if p["gen_method"] == "OUT_OF_SCOPE" and overlap(p["question_text"], p["evidence_text"]) < OOS_MIN_OVERLAP
    ]
    return {
        "answerable_overlap_above": {"limit": ANS_MAX_OVERLAP, "pair_ids": too_high},
        "out_of_scope_overlap_below": {"limit": OOS_MIN_OVERLAP, "pair_ids": too_low},
    }


def quality_report(pairs: list[dict]) -> dict:
    """라벨별 질문 길이 · 질문-근거 단어 겹침 평균과 질문 유형 분포(3.2.4 점검용)."""
    report = {"by_gen_method": {}, "question_type": {}}
    for method in LABEL_OF:
        ps = [p for p in pairs if p["gen_method"] == method]
        if ps:
            report["by_gen_method"][method] = {
                "n": len(ps),
                "mean_len": round(sum(len(p["question_text"]) for p in ps) / len(ps), 1),
                "mean_overlap": round(sum(overlap(p["question_text"], p["evidence_text"]) for p in ps) / len(ps), 3),
                # 의견 말투 지름길 점검: 이 비율이 라벨마다 크게 다르면 모델이 말투만 보고 라벨을 맞힐 수 있다.
                "opinion_cue_rate": round(
                    sum(bool(OPINION_CUE_RE.search(p["question_text"])) for p in ps) / len(ps), 3
                ),
            }
    for p in pairs:
        report["question_type"][p["question_type"]] = report["question_type"].get(p["question_type"], 0) + 1
    return report


def english_term_ratio(text: str) -> float:
    words = text.split()
    return sum(bool(ALPHA_RE.search(w)) for w in words) / len(words) if words else 0.0


def validate_output(row: dict, strict_len: bool = False) -> list[str]:
    """LLM 출력 1행의 형식 오류 목록. 비어 있으면 통과."""
    errs = []
    if not row.get("evidence_id"):
        errs.append("evidence_id 없음")
    if not HANGUL_RE.search(row.get("ko_text", "")):
        errs.append("ko_text가 한국어가 아님")
    if row.get("skip"):
        return errs
    qs = row.get("questions") or []
    methods = [q.get("gen_method") for q in qs]
    if sorted(methods) != sorted(LABEL_OF):
        errs.append(f"gen_method 구성이 다름: {methods}")
    for q in qs:
        if not HANGUL_RE.search(q.get("question_text", "")):
            errs.append(f"질문이 한국어가 아님: {q.get('question_text')}")
        if q.get("question_type") not in QUESTION_TYPES:
            errs.append(f"question_type 오류: {q.get('question_type')}")
        if q.get("gen_method") == "OPINION" and q.get("question_type") != "의견":
            errs.append("OPINION인데 question_type이 의견이 아님")
        n = len(q.get("question_text", ""))
        if strict_len and not QUESTION_LEN[0] <= n <= QUESTION_LEN[1]:
            errs.append(f"질문 길이 {n}자가 {QUESTION_LEN[0]}~{QUESTION_LEN[1]}자 밖: {q.get('question_text')}")
    return errs


def to_pairs(row: dict, src: dict, batch_id: str) -> list[dict]:
    """검증을 통과한 LLM 출력 1행 → 3.3.3 학습 쌍."""
    pairs = []
    for i, q in enumerate(row.get("questions") or [], start=1):
        label = LABEL_OF[q["gen_method"]]
        pairs.append(
            {
                "pair_id": f"{batch_id}:{row['evidence_id']}:q{i}",
                "course_id": src["course_id"],
                "lecture_id": src["lecture_id"],
                "question_text": q["question_text"],
                "evidence_text": row["ko_text"],
                "evidence_type": "TRANSCRIPT",
                "evidence_id": row["evidence_id"],
                "page_no": None,
                "start_ms": None,
                "end_ms": None,
                "label": label,
                "target": int(label == "ANSWERABLE"),
                "label_source": "LLM",
                "source": "MIT_OCW",
                "question_source": "SYNTHETIC",
                "gen_method": q["gen_method"],
                "is_hard_negative": False,
                "contains_aihub": False,
                "split": SPLIT_OF[src["course_id"]],
                "dataset_version": None,
                "question_lang": "ko",
                "evidence_lang": "ko",
                "question_type": q["question_type"],
                "has_english_term": english_term_ratio(q["question_text"]) > 0,
                "answer_hint": q.get("answer_hint", ""),
            }
        )
    return pairs


def cmd_prepare(args) -> None:
    courses = sorted({lid.rsplit("_", 1)[0] for lid in args.lectures}) if args.lectures else [args.course]
    if not courses or None in courses:
        sys.exit("--course 또는 --lectures가 필요합니다.")
    for course in courses:
        if course not in SPLIT_OF:
            sys.exit(f"{course}는 한국어 변환 대상이 아닙니다(시험 강좌는 영어 원문 그대로, 설계서 3.2.2).")
    if args.lectures:
        picked = lecture_chunks(args.chunks, args.lectures)
    else:
        picked = select_chunks(read_jsonl(args.chunks / f"{args.course}.jsonl"), args.n, args.seed, set(args.exclude))
    out = args.root / args.batch
    out.mkdir(parents=True, exist_ok=True)
    targets = assign_target_types([c["evidence_text"] for c in picked], args.seed)
    rows = [
        {**{k: c[k] for k in ("evidence_id", "lecture_id", "course_id", "evidence_text")}, "target_types": t}
        for c, t in zip(picked, targets, strict=True)
    ]
    write_jsonl(out / "input.jsonl", rows)
    if args.part_size:
        # 구독 한도 창마다 나눠 돌리기 위한 묶음 파일. LLM은 parts/in_NN.jsonl → parts/out_NN.jsonl을 만든다.
        (out / "parts").mkdir(exist_ok=True)
        for i in range(0, len(rows), args.part_size):
            write_jsonl(out / "parts" / f"in_{i // args.part_size + 1:02d}.jsonl", rows[i : i + args.part_size])
    meta = {
        "batch_id": args.batch,
        "created": dt.date.today().isoformat(),
        "course_id": courses[0] if len(courses) == 1 else courses,
        "lectures": sorted(args.lectures) if args.lectures else None,
        "part_size": args.part_size or None,
        "seed": args.seed,
        "excluded_lectures": sorted(args.exclude),
        "prompts": {"rewrite": args.rewrite_prompt, "questions": args.question_prompt},
        "source_evidence_ids": [c["evidence_id"] for c in picked],
        "model": None,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(picked)}개 청크 → {out / 'input.jsonl'}")


def meta_prompts(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "meta.json").read_text(encoding="utf-8")).get("prompts", {})


def cmd_ingest(args) -> None:
    out = args.root / args.batch
    src = {r["evidence_id"]: r for r in read_jsonl(out / "input.jsonl")}
    rows = read_jsonl(out / "output.jsonl")
    errors, pairs, skipped, no_content = {}, [], [], []
    for row in rows:
        eid = row.get("evidence_id")
        if eid not in src:
            errors[str(eid)] = ["입력에 없는 evidence_id"]
            continue
        strict = meta_prompts(out).get("questions", "") >= "question_synth_v2"
        if errs := validate_output(row, strict_len=strict):
            errors[eid] = errs
            continue
        if row.get("content") is False:
            no_content.append(eid)
        if row.get("skip"):
            skipped.append(eid)
            continue
        pairs.extend(to_pairs(row, src[eid], args.batch))
    missing = sorted(set(src) - {r.get("evidence_id") for r in rows})
    write_jsonl(out / "pairs.jsonl", pairs)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    meta.update(
        {
            "model": args.model,
            "generated": dt.date.today().isoformat(),
            "outputs": len(rows),
            "pairs": len(pairs),
            "skipped_no_question": skipped,
            "flagged_no_content": no_content,
            "missing": missing,
            "errors": errors,
            "quality": quality_report(pairs),
            "overlap_warnings": overlap_warnings(pairs),
        }
    )
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"출력 {len(rows)}행 · 쌍 {len(pairs)}개 · 제외 {len(skipped)} · 누락 {len(missing)} · 오류 {len(errors)}")
    for eid, errs in errors.items():
        print(f"  {eid}: {'; '.join(errs)}")
    print(json.dumps(meta["quality"], ensure_ascii=False, indent=2))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/interim/synth"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--batch", required=True)
    p.add_argument("--course", help="강좌에서 --n개를 무작위로 고를 때")
    p.add_argument("--lectures", nargs="*", default=None, help="이 강의들의 청크 전부(강좌 여럿 가능)")
    p.add_argument("--part-size", type=int, default=0, help="이 크기로 parts/in_NN.jsonl 묶음도 만든다")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=20261111)
    p.add_argument("--chunks", type=Path, default=Path("data/interim/mit_ocw/chunks"))
    p.add_argument("--exclude", nargs="*", default=[], help="뺄 lecture_id (예: 예비 샘플에 쓴 강의)")
    p.add_argument("--rewrite-prompt", default=DEFAULT_PROMPTS["rewrite"])
    p.add_argument("--question-prompt", default=DEFAULT_PROMPTS["questions"])
    i = sub.add_parser("ingest")
    i.add_argument("--batch", required=True)
    i.add_argument("--model", required=True, help="실제로 생성한 모델 ID")
    args = parser.parse_args()
    {"prepare": cmd_prepare, "ingest": cmd_ingest}[args.cmd](args)


if __name__ == "__main__":
    main()
