"""SQuAD 2.0 train에서 학습 쌍 500개(답 있음 250 + 답 없음 250)를 뽑고 지문을 근거 길이로 자른다 (설계서 3.1.2, 3.2.3).

- 라벨: is_impossible false → ANSWERABLE, true → INSUFFICIENT_EVIDENCE (label_source PUBLIC).
- 고르기: seed로 섞은 뒤 한 지문(paragraph)에서 질문 하나, 한 문서(title)에서 라벨별 최대 --per-title개.
  답 없는 질문은 plausible_answers가 있는 것만(자를 위치가 필요).
- 자르기: 답 있음은 정답이 든 문장, 답 없음은 plausible_answers가 가리키는 문장을 가운데 두고
  앞뒤 문장을 번갈아 붙여 --target-words(기본 148단어, 회의안건 B5 추천: 교안 조각 중앙값)에 닿을 때까지 늘린다.
  bge-m3 기준 --max-tokens(기본 350, 교안 조각 최대치)를 넘는 문장은 붙이지 않는다.
- 검증 · 시험셋에는 넣지 않는다(split TRAIN 고정).

입력:  data/raw/squad2/train-v2.0.json
출력:  data/interim/squad2/<이름>/pairs.jsonl (3.3.3 필드), meta.json

사용:
    uv run python scripts/data/squad_sample.py
    uv run python scripts/data/squad_sample.py --name sample-500 --seed 20261121 --tokenizer <bge-m3 폴더>
"""

import argparse
import datetime as dt
import json
import random
import re
import statistics
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from ocw_slide_chunks import MAX_TOKENS, TOKENIZER, TokenCounter

TARGET_WORDS = 148
# 문장 끝: 마침표 · 물음표 · 느낌표(닫는 따옴표 · 괄호 포함) 뒤 공백 + 대문자 · 숫자 · 따옴표로 시작
SENT_RE = re.compile(r"(?<=[.?!])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """문장마다 (시작, 끝) 글자 위치."""
    spans, start = [], 0
    for m in SENT_RE.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def cut_around(
    context: str, char_pos: int, count: Callable[[str], int], target_words: int, max_tokens: int
) -> tuple[str, int]:
    """char_pos가 든 문장을 가운데 두고 앞뒤 문장을 번갈아 붙인다. (잘린 지문, 시작 글자 위치)"""
    spans = sentence_spans(context)
    k = next((i for i, (s, e) in enumerate(spans) if s <= char_pos < e), len(spans) - 1)
    lo = hi = k

    def text(a: int, b: int) -> str:
        return context[spans[a][0] : spans[b][1]]

    right = True
    while len(text(lo, hi).split()) < target_words:
        can_r, can_l = hi + 1 < len(spans), lo > 0
        if not (can_r or can_l):
            break
        if (right and can_r) or not can_l:
            if count(text(lo, hi + 1)) > max_tokens:
                if not can_l or count(text(lo - 1, hi)) > max_tokens:
                    break
                lo -= 1
            else:
                hi += 1
        else:
            if count(text(lo - 1, hi)) > max_tokens:
                if not can_r or count(text(lo, hi + 1)) > max_tokens:
                    break
                hi += 1
            else:
                lo -= 1
        right = not right
    return text(lo, hi).strip(), spans[lo][0]


def candidates(data: list[dict]) -> list[dict]:
    """(문서, 지문, 질문) 후보. 답 없는 질문은 plausible_answers가 있는 것만."""
    out = []
    for article in data:
        for p_idx, para in enumerate(article["paragraphs"]):
            for qa in para["qas"]:
                answers = qa["plausible_answers"] if qa["is_impossible"] else qa["answers"]
                if not answers:
                    continue
                out.append(
                    {
                        "title": article["title"],
                        "para_key": f"{article['title']}#{p_idx}",
                        "context": para["context"],
                        "qid": qa["id"],
                        "question": qa["question"].strip(),
                        "impossible": qa["is_impossible"],
                        "answer": answers[0],
                    }
                )
    return out


def sample(
    cands: list[dict], n_per_label: int, seed: int, per_title: int, make: Callable[[dict], dict | None]
) -> tuple[list[dict], list[str]]:
    """seed로 섞어 라벨별 n_per_label개를 고른다. make가 None을 돌려주면(자르기 실패) 빼고 다음 후보로."""
    pool = sorted(cands, key=lambda c: c["qid"])
    random.Random(seed).shuffle(pool)
    used_para, per = set(), Counter()
    picked: dict[bool, list[dict]] = {False: [], True: []}
    dropped = []
    for c in pool:
        lab = c["impossible"]
        if len(picked[lab]) >= n_per_label or c["para_key"] in used_para or per[(c["title"], lab)] >= per_title:
            continue
        if (pair := make(c)) is None:
            dropped.append(c["qid"])
            continue
        picked[lab].append(pair)
        used_para.add(c["para_key"])
        per[(c["title"], lab)] += 1
        if all(len(v) >= n_per_label for v in picked.values()):
            break
    return picked[False] + picked[True], dropped


def to_pair(c: dict, evidence: str) -> dict:
    label = "INSUFFICIENT_EVIDENCE" if c["impossible"] else "ANSWERABLE"
    return {
        "pair_id": f"squad:{c['qid']}",
        "course_id": None,
        "lecture_id": None,
        "question_text": c["question"],
        "evidence_text": evidence,
        "evidence_type": "DOCUMENT",
        "evidence_id": f"squad-{c['qid']}-1",
        "page_no": None,
        "start_ms": None,
        "end_ms": None,
        "label": label,
        "target": int(label == "ANSWERABLE"),
        "label_source": "PUBLIC",
        "source": "SQUAD",
        "question_source": "PUBLIC",
        "gen_method": "PUBLIC",
        "is_hard_negative": False,
        "contains_aihub": False,
        "split": "TRAIN",
        "dataset_version": None,
        "question_lang": "en",
        "evidence_lang": "en",
        "question_type": None,
        "has_english_term": None,
        "squad_title": c["title"],
        "anchor_text": c["answer"]["text"],
    }


def build(
    data: list[dict], count: Callable[[str], int], n_per_label: int, seed: int, per_title: int,
    target_words: int, max_tokens: int,
) -> tuple[list[dict], dict]:
    def make(c: dict) -> dict | None:
        evidence, start = cut_around(c["context"], c["answer"]["answer_start"], count, target_words, max_tokens)
        a0 = c["answer"]["answer_start"] - start
        # 정답(답 없음은 plausible 답)이 잘린 지문 안에 그대로 남았는지 확인한다.
        if evidence[a0 : a0 + len(c["answer"]["text"])] != c["answer"]["text"]:
            return None
        return to_pair(c, evidence)

    pairs, dropped = sample(candidates(data), n_per_label, seed, per_title, make)
    stats = {}
    for lab in ("ANSWERABLE", "INSUFFICIENT_EVIDENCE"):
        ps = [p for p in pairs if p["label"] == lab]
        if ps:
            words = [len(p["evidence_text"].split()) for p in ps]
            toks = [count(p["evidence_text"]) for p in ps]
            stats[lab] = {
                "n": len(ps),
                "evidence_words_median": statistics.median(words),
                "evidence_words_min_max": [min(words), max(words)],
                "evidence_tokens_max": max(toks),
                "titles": len({p["squad_title"] for p in ps}),
            }
    return pairs, {"dropped_anchor_mismatch": dropped, "by_label": stats}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", type=Path, default=Path("data/raw/squad2/train-v2.0.json"))
    ap.add_argument("--out-root", type=Path, default=Path("data/interim/squad2"))
    ap.add_argument("--name", default="sample-500")
    ap.add_argument("--n-per-label", type=int, default=250)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--per-title", type=int, default=2, help="문서(title) 하나에서 라벨별 최대 질문 수")
    ap.add_argument("--target-words", type=int, default=TARGET_WORDS)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--tokenizer", default=TOKENIZER)
    args = ap.parse_args()

    tc = TokenCounter(args.tokenizer)
    data = json.loads(args.input.read_text(encoding="utf-8"))["data"]
    pairs, report = build(
        data, tc.count, args.n_per_label, args.seed, args.per_title, args.target_words, args.max_tokens
    )
    out = args.out_root / args.name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "pairs.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for p in pairs:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    meta = {
        "name": args.name,
        "created": dt.date.today().isoformat(),
        "source": str(args.input),
        "license": "CC BY-SA 4.0",
        "params": {k: str(v) for k, v in vars(args).items()},
        "pairs": len(pairs),
        **report,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"쌍 {len(pairs)}개 → {out / 'pairs.jsonl'}")
    print(json.dumps(report["by_label"], ensure_ascii=False, indent=2))
    if report["dropped_anchor_mismatch"]:
        print(f"정답 위치가 어긋나 뺀 질문 {len(report['dropped_anchor_mismatch'])}개")


if __name__ == "__main__":
    main()
