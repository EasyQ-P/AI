"""AI Hub 「기계독해」에서 학습 쌍 500개(정답 있음 250 + 정답 없음 250)를 뽑아 근거 길이로 자른다 (설계서 3.1.2~3.2.3).

- 라벨: 표준(정답 있음) 파일 → ANSWERABLE, 정답 없음 파일 → INSUFFICIENT_EVIDENCE (label_source PUBLIC).
  라벨은 어느 입력(--normal / --noanswer)에서 왔는지로 정하고, 질문에 is_impossible이 있으면 맞는지 확인만 한다.
- 고르기: squad_sample.py와 같다. seed로 섞은 뒤 한 지문에서 질문 하나, 한 문서에서 라벨별 최대 --per-title개.
  같은 지문이 두 파일에 다 있어도 지문 내용으로 묶어 한 번만 쓴다.
- 자르기 (3.1.2):
  정답 있음 = 정답이 든 문장을 가운데 두고 앞뒤 문장을 번갈아 붙인다(SQuAD와 같은 함수, 한국어 문장 나누기).
  정답 없음 = 지문을 근거 길이 조각으로 나누고 질문과 BM25 점수가 가장 높은 조각. 겹치는 낱말이 없으면 뺀다.
  길이 = --target-words(한국어는 어절, 기본 148)까지 늘리되 bge-m3 --max-tokens(기본 350)를 넘지 않는다.
- 실행 위치: 학과 서버가 아니라 데이터를 직접 받은 본인 PC에서 돌리고, 결과를 학과 서버로 올린다
  (설계서 3.1.3과 다름, 결정 기록은 docs/notes/AIHub_다운로드_정리.md). 올린 뒤 PC의 원본 · 결과는 지운다.
- AI Hub 규칙 (3.1.3): 임베딩 · 외부 API를 쓰지 않는다. 이 스크립트는 네트워크를 쓰지 않는다
  (--tokenizer에 bge-m3 로컬 폴더를 주면 토크나이저도 받지 않는다). contains_aihub = true.
- 화면에는 개수 · 통계만 찍는다. 지문 · 질문 · 정답 · 질문 ID는 화면에도 오류 메시지에도 넣지 않는다.
- --inspect: 값 없이 JSON 키 경로 · 타입 · 개수(bool은 값별 개수, 문자열 · 목록은 길이 통계)만 찍는다.

입력:  --normal  01.Normal 압축을 푼 JSON 파일 또는 폴더(하위 *.json 전부)
       --noanswer 02.NoAnswer 압축을 푼 JSON 파일 또는 폴더
       지금은 KorQuAD/SQuAD형(data > paragraphs > context, qas > question, answers[text, answer_start], id)을 가정한다.
       --inspect 결과를 보고 다르면 candidates()의 필드 이름만 고친다.
출력:  data/interim/aihub/<이름>/pairs.jsonl (3.3.3 필드), meta.json

사용:
    uv run python scripts/data/aihub_sample.py --inspect --normal <폴더> --noanswer <폴더>
    uv run python scripts/data/aihub_sample.py --normal <폴더> --noanswer <폴더> --tokenizer <bge-m3 폴더>
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

from ocw_slide_chunks import MAX_TOKENS, TOKENIZER, TokenCounter
from squad_sample import TARGET_WORDS, cut_around, sample

ATTRIBUTION = "본 프로젝트는 한국지능정보사회진흥원의 사업결과인 AI Hub 「기계독해」 데이터를 활용하였다."
LABELS = {False: "ANSWERABLE", True: "INSUFFICIENT_EVIDENCE"}

# 문장 끝: . ? ! (닫는 따옴표 · 괄호 포함) 뒤 공백, 또는 줄바꿈. "3.5"처럼 뒤에 공백이 없으면 나누지 않는다.
SENT_RE = re.compile(r"[.?!][\"'”’)\]」』]*\s+|\n\s*")
WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+")
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
KIWI_TAGS = ("NNG", "NNP", "NR", "VV", "VA", "XR", "SL", "SH", "SN")


# ---------------------------------------------------------------- 문장 · 조각

def sentence_spans_ko(text: str) -> list[tuple[int, int]]:
    """한국어 문장마다 (시작, 끝) 글자 위치. 앞뒤 공백은 뺀다."""
    spans, start = [], 0
    for m in SENT_RE.finditer(text):
        spans.append((start, m.start() + len(m.group().rstrip())))
        start = m.end()
    spans.append((start, len(text)))
    out = []
    for s, e in spans:
        seg = text[s:e]
        if seg.strip():
            out.append((s + len(seg) - len(seg.lstrip()), e - (len(seg) - len(seg.rstrip()))))
    return out


def passage_chunks(context: str, count: Callable[[str], int], target_words: int, max_tokens: int) -> list[str]:
    """지문을 앞에서부터 문장 단위로 묶어 근거 길이 조각으로 나눈다. 한 문장이 max_tokens를 넘으면 그 조각만 길다."""
    chunks: list[str] = []
    cur: tuple[int, int] | None = None
    for s, e in sentence_spans_ko(context):
        if cur is None:
            cur = (s, e)
        elif len(context[cur[0] : cur[1]].split()) < target_words and count(context[cur[0] : e]) <= max_tokens:
            cur = (cur[0], e)
        else:
            chunks.append(context[cur[0] : cur[1]])
            cur = (s, e)
    if cur is not None:
        chunks.append(context[cur[0] : cur[1]])
    return chunks


# ---------------------------------------------------------------- BM25 (임베딩 없이)

def bigram_tokens(text: str) -> list[str]:
    """어절(한글 · 영문 · 숫자)마다 글자 2-gram. 한 글자 어절은 그대로."""
    out: list[str] = []
    for w in WORD_RE.findall(text.lower()):
        out.extend([w] if len(w) < 2 else [w[i : i + 2] for i in range(len(w) - 1)])
    return out


def kiwi_tokenizer() -> Callable[[str], list[str]] | None:
    """kiwipiepy가 있으면 내용어 형태소(명사 · 동사 · 형용사 어간 · 외국어 · 숫자) 토큰. 없으면 None."""
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        return None
    kiwi = Kiwi()

    def tok(text: str) -> list[str]:
        return [t.form.lower() for t in kiwi.tokenize(text) if t.tag.startswith(KIWI_TAGS)]

    return tok


def bm25_scores(query: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25. 말뭉치는 한 지문의 조각들."""
    n = len(docs)
    avg = (sum(len(d) for d in docs) / n) if n else 0.0
    avg = avg or 1.0
    df = Counter(t for d in docs for t in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in set(query):
            if t in tf:
                idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1)
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


# ---------------------------------------------------------------- 읽기

def json_files(path: Path) -> list[Path]:
    return sorted(path.rglob("*.json")) if path.is_dir() else [path]


def load(files: list[Path], issues: Counter) -> Iterator[tuple[str, list]]:
    """(파일 이름, data 목록). 읽기 실패는 개수만 센다(오류 메시지에 내용이 섞일 수 있어 남기지 않는다)."""
    for f in files:
        try:
            obj = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            issues["파일 읽기 실패"] += 1
            continue
        docs = obj.get("data") if isinstance(obj, dict) else None
        if not isinstance(docs, list):
            issues["최상위 data 목록 없음"] += 1
            continue
        yield f.stem, docs


def find_answer(context: str, answers: object, issues: Counter) -> dict | None:
    if not isinstance(answers, list) or not answers or not isinstance(answers[0], dict):
        issues["정답 있음인데 answers 없음"] += 1
        return None
    text, start = answers[0].get("text"), answers[0].get("answer_start")
    if not isinstance(text, str) or not text.strip():
        issues["정답 text 없음"] += 1
        return None
    if isinstance(start, int) and context[start : start + len(text)] == text:
        return {"text": text, "answer_start": start}
    if context.count(text) == 1:
        issues["answer_start 보정(정답이 지문에 한 번만 있음)"] += 1
        return {"text": text, "answer_start": context.index(text)}
    issues["정답 위치를 못 찾음"] += 1
    return None


def candidates(groups: list[tuple[bool, str, list]], issues: Counter) -> list[dict]:
    """(정답 없음 여부, 파일 이름, data 목록) → 질문 후보. 문제가 있는 질문은 이유별 개수만 센다."""
    out, seen = [], set()
    for impossible, fkey, docs in groups:
        for d, doc in enumerate(docs):
            paras = doc.get("paragraphs") if isinstance(doc, dict) else None
            if not isinstance(paras, list):
                issues["paragraphs 없음"] += 1
                continue
            title = doc.get("title")
            title = title.strip() if isinstance(title, str) and title.strip() else f"{fkey}#{d}"
            for p, para in enumerate(paras):
                ctx = para.get("context") if isinstance(para, dict) else None
                qas = para.get("qas") if isinstance(para, dict) else None
                if not isinstance(ctx, str) or not ctx.strip():
                    issues["context 없음"] += 1
                    continue
                if not isinstance(qas, list):
                    issues["qas 없음"] += 1
                    continue
                para_key = hashlib.sha1(ctx.strip().encode("utf-8")).hexdigest()[:16]
                for q, qa in enumerate(qas):
                    question = qa.get("question") if isinstance(qa, dict) else None
                    if not isinstance(question, str) or not question.strip():
                        issues["question 없음"] += 1
                        continue
                    flag = qa.get("is_impossible")
                    if isinstance(flag, bool) and flag != impossible:
                        issues["is_impossible이 입력 종류와 다름"] += 1
                        continue
                    qid = qa.get("id")
                    qid = str(qid) if qid not in (None, "") else f"{fkey}-{d}-{p}-{q}"
                    if qid in seen:
                        issues["질문 id 중복"] += 1
                        continue
                    seen.add(qid)
                    answer = None
                    if not impossible and (answer := find_answer(ctx, qa.get("answers"), issues)) is None:
                        continue
                    out.append(
                        {
                            "title": title,
                            "para_key": para_key,
                            "context": ctx,
                            "qid": qid,
                            "question": question.strip(),
                            "impossible": impossible,
                            "answer": answer,
                        }
                    )
    return out


# ---------------------------------------------------------------- 쌍 만들기

def to_pair(c: dict, evidence: str, bm25_chunk: int | None = None, bm25_chunks: int | None = None) -> dict:
    label = LABELS[c["impossible"]]
    return {
        "pair_id": f"aihub:{c['qid']}",
        "course_id": None,
        "lecture_id": None,
        "question_text": c["question"],
        "evidence_text": evidence,
        "evidence_type": "DOCUMENT",
        "evidence_id": f"aihub-{c['qid']}-1",
        "page_no": None,
        "start_ms": None,
        "end_ms": None,
        "label": label,
        "target": int(label == "ANSWERABLE"),
        "label_source": "PUBLIC",
        "source": "AIHUB",
        "question_source": "PUBLIC",
        "gen_method": "PUBLIC",
        "is_hard_negative": False,
        "contains_aihub": True,
        "split": "TRAIN",
        "dataset_version": None,
        "question_lang": "ko",
        "evidence_lang": "ko",
        "question_type": None,
        "has_english_term": None,
        # 검수용
        "aihub_title": c["title"],
        "anchor_text": c["answer"]["text"] if c["answer"] else None,
        "bm25_chunk": bm25_chunk,
        "bm25_chunks": bm25_chunks,
    }


def build(
    cands: list[dict], count: Callable[[str], int], n_per_label: int, seed: int, per_title: int,
    target_words: int, max_tokens: int, tokenize: Callable[[str], list[str]],
) -> tuple[list[dict], dict]:
    dropped: Counter = Counter()

    def make(c: dict) -> dict | None:
        if c["impossible"]:
            chunks = passage_chunks(c["context"], count, target_words, max_tokens)
            ok = [i for i, ch in enumerate(chunks) if count(ch) <= max_tokens]
            if not ok:
                dropped["정답 없음: 조각이 모두 토큰 상한 초과"] += 1
                return None
            scores = bm25_scores(tokenize(c["question"]), [tokenize(chunks[i]) for i in ok])
            best = max(range(len(ok)), key=lambda j: (scores[j], -j))
            if scores[best] <= 0:
                dropped["정답 없음: 질문과 겹치는 낱말 없음(BM25 0)"] += 1
                return None
            return to_pair(c, chunks[ok[best]], ok[best], len(chunks))
        pos, text = c["answer"]["answer_start"], c["answer"]["text"]
        evidence, start = cut_around(c["context"], pos, count, target_words, max_tokens, split=sentence_spans_ko)
        a0 = pos - start
        if evidence[a0 : a0 + len(text)] != text:
            dropped["정답 있음: 잘린 근거에서 정답 위치 어긋남"] += 1
            return None
        if count(evidence) > max_tokens:
            dropped["정답 있음: 정답 문장 하나가 토큰 상한 초과"] += 1
            return None
        return to_pair(c, evidence)

    pairs, _ = sample(cands, n_per_label, seed, per_title, make)
    stats = {}
    for lab in LABELS.values():
        ps = [p for p in pairs if p["label"] == lab]
        if ps:
            words = [len(p["evidence_text"].split()) for p in ps]
            toks = [count(p["evidence_text"]) for p in ps]
            stats[lab] = {
                "n": len(ps),
                "evidence_eojeol_median": statistics.median(words),
                "evidence_eojeol_min_max": [min(words), max(words)],
                "evidence_tokens_median": statistics.median(toks),
                "evidence_tokens_max": max(toks),
                "titles": len({p["aihub_title"] for p in ps}),
            }
    shortfall = {
        lab: n_per_label - sum(p["label"] == lab for p in pairs)
        for lab in LABELS.values()
        if sum(p["label"] == lab for p in pairs) < n_per_label
    }
    return pairs, {"dropped": dict(dropped), "by_label": stats, "shortfall": shortfall}


# ---------------------------------------------------------------- 구조 보기 (값 없음)

def walk(obj: object, path: str, st: dict) -> None:
    node = st.setdefault(path, {"types": Counter(), "bool": Counter(), "len": []})
    node["types"][type(obj).__name__] += 1
    if isinstance(obj, bool):
        node["bool"][str(obj)] += 1
    elif isinstance(obj, dict):
        for k, v in obj.items():
            # 키 이름이 영문 식별자가 아니면(내용일 수 있음) 이름을 찍지 않는다.
            walk(v, f"{path}.{k if isinstance(k, str) and KEY_RE.match(k) else '<?>'}", st)
    elif isinstance(obj, list):
        node["len"].append(len(obj))
        for v in obj:
            walk(v, f"{path}[]", st)
    elif isinstance(obj, str):
        node["len"].append(len(obj))


def inspect(groups: list[tuple[str, list[Path]]]) -> list[str]:
    lines = []
    for name, files in groups:
        st: dict = {}
        bad = 0
        for f in files:
            try:
                walk(json.loads(f.read_text(encoding="utf-8-sig")), "$", st)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                bad += 1
        lines.append(f"== {name}: JSON 파일 {len(files)}개 (읽기 실패 {bad})")
        for path, node in st.items():
            parts = [path, "타입 " + ", ".join(f"{t}×{n}" for t, n in node["types"].items())]
            if node["bool"]:
                parts.append("값 " + ", ".join(f"{v}×{n}" for v, n in sorted(node["bool"].items())))
            if node["len"]:
                ln = node["len"]
                parts.append(f"길이 {min(ln)}/{statistics.median(ln):g}/{max(ln)}(최소/중앙/최대)")
            lines.append("  " + " | ".join(parts))
    return lines


# ---------------------------------------------------------------- 실행

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--normal", type=Path, required=True, help="표준(정답 있음) JSON 파일 또는 폴더")
    ap.add_argument("--noanswer", type=Path, required=True, help="정답 없음 JSON 파일 또는 폴더")
    ap.add_argument("--inspect", action="store_true", help="값 없이 키 구조만 찍고 끝낸다")
    ap.add_argument("--out-root", type=Path, default=Path("data/interim/aihub"))
    ap.add_argument("--name", default="sample-500")
    ap.add_argument("--n-per-label", type=int, default=250)
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--per-title", type=int, default=2, help="문서 하나에서 라벨별 최대 질문 수")
    ap.add_argument("--target-words", type=int, default=TARGET_WORDS, help="목표 길이(어절)")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--tokenizer", default=TOKENIZER)
    ap.add_argument("--bm25", choices=["auto", "kiwi", "bigram"], default="auto",
                    help="BM25 토큰: auto = kiwipiepy가 있으면 kiwi, 없으면 글자 2-gram")
    args = ap.parse_args()

    files = {"normal": json_files(args.normal), "noanswer": json_files(args.noanswer)}
    if empty := [k for k, v in files.items() if not v]:
        sys.exit(f"JSON 파일이 없습니다: {', '.join(empty)}. 경로 · 압축 해제(안에 zip이 또 있는지)를 확인하세요.")

    if args.inspect:
        for line in inspect(list(files.items())):
            print(line)
        return

    kiwi = kiwi_tokenizer() if args.bm25 in ("auto", "kiwi") else None
    if args.bm25 == "kiwi" and kiwi is None:
        sys.exit("kiwipiepy가 없습니다. --bm25 bigram으로 돌리거나 설치하세요.")
    tokenize, bm25_name = (kiwi, "kiwi") if kiwi else (bigram_tokens, "bigram")

    issues: Counter = Counter()
    groups = []
    for impossible, key in ((False, "normal"), (True, "noanswer")):
        tag = "X" if impossible else "N"
        for fkey, docs in load(files[key], issues):
            groups.append((impossible, f"{tag}:{fkey}", docs))
    cands = candidates(groups, issues)
    cand_counts = {LABELS[k]: v for k, v in sorted(Counter(c["impossible"] for c in cands).items())}

    tc = TokenCounter(args.tokenizer)
    pairs, report = build(
        cands, tc.count, args.n_per_label, args.seed, args.per_title, args.target_words, args.max_tokens, tokenize
    )
    out = args.out_root / args.name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "pairs.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for p in pairs:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    meta = {
        "name": args.name,
        "created": dt.date.today().isoformat(),
        "source": {"normal": str(args.normal), "noanswer": str(args.noanswer)},
        "attribution": ATTRIBUTION,
        "contains_aihub": True,
        "params": {k: str(v) for k, v in vars(args).items()},
        "bm25_tokenizer": bm25_name,
        "pairs": len(pairs),
        "candidates": cand_counts,
        "issues": dict(issues),
        **report,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"쌍 {len(pairs)}개 → {out / 'pairs.jsonl'} (BM25 토큰: {bm25_name})")
    print("후보 질문 수:", json.dumps(cand_counts, ensure_ascii=False))
    print(json.dumps(report["by_label"], ensure_ascii=False, indent=2))
    if issues:
        print("입력 문제 · 보정:", json.dumps(dict(issues), ensure_ascii=False, indent=2))
    if report["dropped"]:
        print("자르기에서 뺀 질문:", json.dumps(report["dropped"], ensure_ascii=False, indent=2))
    if report["shortfall"]:
        print("모자란 개수:", json.dumps(report["shortfall"], ensure_ascii=False))


if __name__ == "__main__":
    main()
