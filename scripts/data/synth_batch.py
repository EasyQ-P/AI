"""LLM 합성 배치 준비 · 검증 (설계서 3.2.2 (1) 4단계 한국어 변환, 3.3.4 학습셋 3 · 4단계 질문 합성 · 1차 라벨).

LLM 호출은 이 스크립트 밖에서 한다(Sonnet). 이 스크립트는
  prepare: 청크를 골라 배치 입력(input.jsonl)과 메타(meta.json)를 만들고
  ingest:  LLM 출력(output.jsonl)을 검사해 3.3.3 필드의 학습 쌍(pairs.jsonl)으로 바꾼다.

두 가지 근거를 다룬다(--source).
  transcript(기본): 발화 청크 → 한국어 구어체 변환(ko_rewrite) → 질문. 근거는 한국어 변환본, TRANSCRIPT.
  slides: 교안 조각(slides-v4, 400토큰 · 겹침 50) → 질문. 근거는 번역 없이 영어 원문, DOCUMENT · page_no.
          evidence_id는 교안 조각의 source_key. 2026-11-25 B안(OCW 700/700/600 안에서 교안 쌍으로 일부 교체).

배치 폴더: data/interim/synth/<batch_id>/  (커밋 금지)
  input.jsonl   evidence_id, lecture_id, course_id, evidence_text(영어 원문), target_types
                (slides는 evidence_type DOCUMENT, page_no도)
  output.jsonl  LLM 출력: evidence_id, ko_text(transcript만), content, skip,
                questions[gen_method, question_text, question_type, answer_hint]
  pairs.jsonl   학습 쌍(3.3.3)
  meta.json     모델 ID, 날짜, 프롬프트 버전, 원본 청크 ID, 제외 개수

사용:
    uv run python scripts/data/synth_batch.py prepare --batch trial-6.006-v1 --course 6.006_S20 --n 30
    uv run python scripts/data/synth_batch.py ingest --batch trial-6.006-v1 --model <모델 ID>
    # 고른 강의의 청크 전부(회의안건 B3), 50청크씩 묶음 파일(parts/in_NN.jsonl)도 만든다
    uv run python scripts/data/synth_batch.py prepare --batch train-ocw-v3_1 \
        --lectures 6.006_S20_L07 6.006_S20_L13 --question-prompt question_synth_v3_1 --part-size 50
    # 교안 조각: 학습 강좌 3개에서 seed로 n개(질문 합성 프롬프트 기본값 question_synth_slides_v1)
    uv run python scripts/data/synth_batch.py prepare --source slides --batch train-slides-v1 \
        --courses 6.006_S20 6.034_F10 6.046J_S15 --n 200 --balance-courses --part-size 50
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
DEFAULT_SLIDE_PROMPT = "question_synth_slides_v1"
# 질문 15~35자 검사를 하지 않는 옛 프롬프트(그 뒤 프롬프트는 모두 검사)
LOOSE_LEN_PROMPTS = {"question_synth_v1"}
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


def balanced_select(chunks: list[dict], n: int, seed: int, exclude_lectures: set[str]) -> list[dict]:
    """강좌마다 되도록 같은 수를 뽑는다. 조각이 모자란 강좌는 전부 쓰고 남은 몫을 다른 강좌에 넘긴다.

    적은 강좌부터 남은 개수 ÷ 남은 강좌 수만큼 배정한다(같은 입력이면 같은 결과).
    """
    by_course: dict[str, list[dict]] = {}
    for c in chunks:
        by_course.setdefault(c["course_id"], []).append(c)
    pools = {
        course: [c for c in cs if c["lecture_id"].rsplit("_", 1)[-1].startswith("L")
                 and c["lecture_id"] not in exclude_lectures]
        for course, cs in by_course.items()
    }
    order = sorted(pools, key=lambda k: (len(pools[k]), k))
    picked, remaining = [], n
    for i, course in enumerate(order):
        take = min(remaining // (len(order) - i), len(pools[course]))
        picked += select_chunks(pools[course], take, seed, exclude_lectures)
        remaining -= take
    return sorted(picked, key=lambda c: c["evidence_id"])


def lecture_chunks(chunks_dir: Path, lectures: list[str]) -> list[dict]:
    """고른 강의의 청크 전부(회의안건 B3: 강의 단위로 고르고 고른 강의는 전부 변환). 강좌가 여럿이어도 된다."""
    want = set(lectures)
    courses = sorted({lid.rsplit("_", 1)[0] for lid in want})
    picked = [c for course in courses for c in read_jsonl(chunks_dir / f"{course}.jsonl") if c["lecture_id"] in want]
    if missing := want - {c["lecture_id"] for c in picked}:
        sys.exit(f"청크가 없는 강의: {sorted(missing)}")
    return sorted(picked, key=lambda c: c["evidence_id"])


def slide_rows(rows: list[dict]) -> list[dict]:
    """slides-v4 교안 조각 행 → 배치 입력 형식(evidence_id = source_key, DOCUMENT, page_no)."""
    return [
        {
            "evidence_id": r["source_key"],
            "lecture_id": r["lecture_id"],
            "course_id": r["lecture_id"].rsplit("_", 1)[0],
            "evidence_type": "DOCUMENT",
            "page_no": r["page_no"],
            "evidence_text": r["text"],
        }
        for r in rows
    ]


def slide_chunks(slides_dir: Path, courses: list[str], lectures: list[str] | None) -> list[dict]:
    """강좌들의 교안 조각. lectures를 주면 그 강의만, 없으면 강좌 전체."""
    rows = [r for course in courses for r in read_jsonl(slides_dir / f"{course}.jsonl")]
    if lectures:
        want = set(lectures)
        rows = [r for r in rows if r["lecture_id"] in want]
        if missing := want - {r["lecture_id"] for r in rows}:
            sys.exit(f"교안 조각이 없는 강의: {sorted(missing)}")
    return slide_rows(rows)


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
    # 영어 교안 근거는 한국어 질문과 단어 단위로 겹칠 수 없어(영어 용어만 겹침) 이 확인선을 쓰지 않는다.
    ko = [p for p in pairs if p.get("evidence_lang", "ko") == "ko"]
    too_high = [
        p["pair_id"]
        for p in ko
        if p["gen_method"] == "ANSWERABLE" and overlap(p["question_text"], p["evidence_text"]) > ANS_MAX_OVERLAP
    ]
    too_low = [
        p["pair_id"]
        for p in ko
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


def validate_output(row: dict, strict_len: bool = False, need_ko_text: bool = True) -> list[str]:
    """LLM 출력 1행의 형식 오류 목록. 비어 있으면 통과. 교안(slides)은 ko_text가 없다(need_ko_text=False)."""
    errs = []
    if not row.get("evidence_id"):
        errs.append("evidence_id 없음")
    if need_ko_text and not HANGUL_RE.search(row.get("ko_text", "")):
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
    """검증을 통과한 LLM 출력 1행 → 3.3.3 학습 쌍. 교안(DOCUMENT)은 영어 원문을 근거로 쓴다."""
    doc = src.get("evidence_type") == "DOCUMENT"
    pairs = []
    for i, q in enumerate(row.get("questions") or [], start=1):
        label = LABEL_OF[q["gen_method"]]
        pairs.append(
            {
                "pair_id": f"{batch_id}:{row['evidence_id']}:q{i}",
                "course_id": src["course_id"],
                "lecture_id": src["lecture_id"],
                "question_text": q["question_text"],
                "evidence_text": src["evidence_text"] if doc else row["ko_text"],
                "evidence_type": "DOCUMENT" if doc else "TRANSCRIPT",
                "evidence_id": row["evidence_id"],
                "page_no": src.get("page_no") if doc else None,
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
                "evidence_lang": "en" if doc else "ko",
                "question_type": q["question_type"],
                "has_english_term": english_term_ratio(q["question_text"]) > 0,
                "answer_hint": q.get("answer_hint", ""),
            }
        )
    return pairs


SLIDE_TASK = """# 묶음 작업 지시 ({batch}, 교안 조각)
입력 파일 parts/in_NN.jsonl(묶음이 없으면 input.jsonl)의 각 줄(영어 교안 조각 하나)마다 출력 한 줄을 만들어
parts/out_NN.jsonl(또는 output.jsonl)에 쓴다(입력과 같은 순서, 줄 수 같게).

각 조각에 대해:
1. 번역하지 않는다. ko_text를 만들지 않는다(근거는 영어 원문 그대로 학습에 들어간다).
2. {prompt}.md 규칙대로 evidence_text만 보고 질문 3개(ANSWERABLE, OUT_OF_SCOPE, OPINION)를 만든다.
   target_types는 참고용. 말투 섞기의 줄 번호 i는 그 파일 안에서 0부터 센다.
3. 출력 한 줄(JSON, ensure_ascii=False). questions의 각 항목은
   gen_method, question_text, question_type, type_changed, answer_hint를 가진다(OPINION의 answer_hint는 ""):
{{"evidence_id": "...", "content": true, "skip": false, "questions": [
 {{"gen_method": "ANSWERABLE", "question_text": "...", "question_type": "...", ...}},
 {{"gen_method": "OUT_OF_SCOPE", "question_text": "...", "question_type": "...", ...}},
 {{"gen_method": "OPINION", "question_text": "...", "question_type": "의견", ...}}]}}
 강의 내용이 없는 조각(제목 · 목차 · 소개 · 참고문헌 · 저작권 문구뿐)은 "content": false, "skip": true, "questions": [].

규칙: 질문은 15~35자(공백 포함). question_type은 개념·방법·이유·비교·예시·운영·의견 중 하나.
스크립트나 다른 모델 호출로 생성하지 말고 직접 작성한다. 파일 쓰기는 Python json.dumps(ensure_ascii=False).
끝나면 줄 수와 JSON 파싱을 확인하고, 15~35자 밖 질문이 있으면 고친다.
"""


def cmd_prepare(args) -> None:
    slides = args.source == "slides"
    if args.lectures:
        courses = sorted({lid.rsplit("_", 1)[0] for lid in args.lectures})
    elif slides:
        courses = sorted(args.courses or ([args.course] if args.course else []))
    else:
        courses = [args.course] if args.course else []
    if not courses:
        sys.exit("--lectures 또는 --course(교안은 --courses도 가능)가 필요합니다.")
    for course in courses:
        if course not in SPLIT_OF:
            sys.exit(f"{course}는 학습 · 검증 강좌가 아닙니다(시험 강좌는 합성하지 않음, 설계서 3.3.4).")
    if slides:
        pool = slide_chunks(args.slides, courses, args.lectures)
        if args.lectures:
            picked = pool
        elif args.balance_courses:
            picked = balanced_select(pool, args.n, args.seed, set(args.exclude))
        else:
            picked = select_chunks(pool, args.n, args.seed, set(args.exclude))
    elif args.lectures:
        picked = lecture_chunks(args.chunks, args.lectures)
    else:
        picked = select_chunks(read_jsonl(args.chunks / f"{args.course}.jsonl"), args.n, args.seed, set(args.exclude))
    question_prompt = args.question_prompt or (DEFAULT_SLIDE_PROMPT if slides else DEFAULT_PROMPTS["questions"])
    out = args.root / args.batch
    out.mkdir(parents=True, exist_ok=True)
    targets = assign_target_types([c["evidence_text"] for c in picked], args.seed)
    keys = ("evidence_id", "lecture_id", "course_id", "evidence_type", "page_no", "evidence_text") if slides else (
        "evidence_id", "lecture_id", "course_id", "evidence_text")
    rows = [{**{k: c[k] for k in keys}, "target_types": t} for c, t in zip(picked, targets, strict=True)]
    if slides:
        (out / "TASK.md").write_text(SLIDE_TASK.format(batch=args.batch, prompt=question_prompt), encoding="utf-8")
    write_jsonl(out / "input.jsonl", rows)
    if args.part_size:
        # 구독 한도 창마다 나눠 돌리기 위한 묶음 파일. LLM은 parts/in_NN.jsonl → parts/out_NN.jsonl을 만든다.
        (out / "parts").mkdir(exist_ok=True)
        for i in range(0, len(rows), args.part_size):
            write_jsonl(out / "parts" / f"in_{i // args.part_size + 1:02d}.jsonl", rows[i : i + args.part_size])
    meta = {
        "batch_id": args.batch,
        "created": dt.date.today().isoformat(),
        "source": args.source,
        "slides_dir": str(args.slides) if slides else None,
        "course_id": courses[0] if len(courses) == 1 else courses,
        "lectures": sorted(args.lectures) if args.lectures else None,
        "part_size": args.part_size or None,
        "seed": args.seed,
        "balance_courses": bool(slides and args.balance_courses and not args.lectures),
        "by_course": {k: sum(c["course_id"] == k for c in picked) for k in courses},
        "excluded_lectures": sorted(args.exclude),
        "prompts": {"rewrite": None if slides else args.rewrite_prompt, "questions": question_prompt},
        "source_evidence_ids": [c["evidence_id"] for c in picked],
        "model": None,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    kind = "교안 조각" if slides else "청크"
    print(f"{len(picked)}개 {kind} → {out / 'input.jsonl'} (질문 프롬프트 {question_prompt})")


def cmd_ingest(args) -> None:
    out = args.root / args.batch
    src = {r["evidence_id"]: r for r in read_jsonl(out / "input.jsonl")}
    rows = read_jsonl(out / "output.jsonl")
    batch_meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    strict = batch_meta.get("prompts", {}).get("questions") not in LOOSE_LEN_PROMPTS
    need_ko = batch_meta.get("source", "transcript") != "slides"
    errors, pairs, skipped, no_content = {}, [], [], []
    for row in rows:
        eid = row.get("evidence_id")
        if eid not in src:
            errors[str(eid)] = ["입력에 없는 evidence_id"]
            continue
        if errs := validate_output(row, strict_len=strict, need_ko_text=need_ko):
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
    meta = batch_meta
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
    p.add_argument("--source", choices=["transcript", "slides"], default="transcript",
                   help="transcript = 발화 청크(한국어 변환), slides = 교안 조각(영어 원문, DOCUMENT)")
    p.add_argument("--course", help="강좌에서 --n개를 무작위로 고를 때")
    p.add_argument("--courses", nargs="*", default=None, help="slides: 여러 강좌를 합쳐 --n개를 무작위로 고를 때")
    p.add_argument("--slides", type=Path, default=Path("data/interim/mit_ocw/slides-v4"))
    p.add_argument("--balance-courses", action="store_true",
                   help="slides --courses: 강좌마다 되도록 같은 수(모자란 강좌는 전부, 남는 몫은 다른 강좌로)")
    p.add_argument("--lectures", nargs="*", default=None, help="이 강의들의 청크 전부(강좌 여럿 가능)")
    p.add_argument("--part-size", type=int, default=0, help="이 크기로 parts/in_NN.jsonl 묶음도 만든다")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=20261111)
    p.add_argument("--chunks", type=Path, default=Path("data/interim/mit_ocw/chunks"))
    p.add_argument("--exclude", nargs="*", default=[], help="뺄 lecture_id (예: 예비 샘플에 쓴 강의)")
    p.add_argument("--rewrite-prompt", default=DEFAULT_PROMPTS["rewrite"])
    p.add_argument("--question-prompt", default=None,
                   help=f"기본값: transcript {DEFAULT_PROMPTS['questions']}, slides {DEFAULT_SLIDE_PROMPT}")
    i = sub.add_parser("ingest")
    i.add_argument("--batch", required=True)
    i.add_argument("--model", required=True, help="실제로 생성한 모델 ID")
    args = parser.parse_args()
    {"prepare": cmd_prepare, "ingest": cmd_ingest}[args.cmd](args)


if __name__ == "__main__":
    main()
