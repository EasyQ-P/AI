"""AI Hub 전처리 테스트. 데이터는 전부 지어낸 예시다(실제 AI Hub 내용 없음)."""

import json
import sys
from collections import Counter

import aihub_sample
from aihub_sample import (
    bigram_tokens,
    bm25_scores,
    build,
    candidates,
    inspect,
    passage_chunks,
    sentence_spans_ko,
)
from build_splits import TRAIN_FIELDS


def count(text: str) -> int:
    return len(text.split())


def normal_docs(n_docs: int = 6, n_paras: int = 3) -> list[dict]:
    docs = []
    for t in range(n_docs):
        paras = []
        for p in range(n_paras):
            ctx = (f"이 글은 가상의 마을{t}{p}에 대한 설명입니다. "
                   f"마을의 특산물은 사과{t}{p}입니다. 주민들은 매년 축제를 엽니다.")
            ans = f"사과{t}{p}"
            paras.append({"context": ctx, "qas": [
                {"id": f"QID-n{t}{p}", "question": "마을의 특산물은 무엇인가요?", "is_impossible": False,
                 "answers": [{"text": ans, "answer_start": ctx.index(ans)}]},
            ]})
        docs.append({"title": f"가상 문서 N{t}", "paragraphs": paras})
    return docs


def noanswer_docs(n_docs: int = 6, n_paras: int = 3, question: str = "시장은 언제 열리나요?") -> list[dict]:
    docs = []
    for t in range(n_docs):
        paras = []
        for p in range(n_paras):
            ctx = f"가상의 도시{t}{p}는 강을 끼고 있습니다. 인구는 꾸준히 늘고 있습니다. 시장은 매주 열립니다."
            paras.append({"context": ctx, "qas": [
                {"id": f"QID-x{t}{p}", "question": question, "is_impossible": True, "answers": []},
            ]})
        docs.append({"title": f"가상 문서 X{t}", "paragraphs": paras})
    return docs


def groups(question: str = "시장은 언제 열리나요?") -> list:
    return [(False, "N:f", normal_docs()), (True, "X:f", noanswer_docs(question=question))]


def test_sentence_spans_ko():
    text = '첫 문장입니다. 그는 "좋다." 라고 했다. 값은 3.5입니다\n  마지막 줄  '
    assert [text[s:e] for s, e in sentence_spans_ko(text)] == [
        "첫 문장입니다.", '그는 "좋다."', "라고 했다.", "값은 3.5입니다", "마지막 줄"]


def test_passage_chunks_target_and_cap():
    ctx = "가 나. 다 라. 마 바. 사 아."
    assert passage_chunks(ctx, count, target_words=4, max_tokens=100) == ["가 나. 다 라.", "마 바. 사 아."]
    assert passage_chunks(ctx, count, target_words=4, max_tokens=3) == ["가 나.", "다 라.", "마 바.", "사 아."]


def test_bm25_prefers_overlap():
    assert bigram_tokens("시장은 A1") == ["시장", "장은", "a1"]
    s = bm25_scores(["시장"], [["도시", "인구"], ["시장", "매주"]])
    assert s[1] > s[0] == 0


def test_build_balanced_fields_and_deterministic():
    issues = Counter()
    cands = candidates(groups(), issues)
    assert not issues
    args = dict(count=count, n_per_label=4, seed=1, per_title=1, target_words=50, max_tokens=350,
                tokenize=bigram_tokens)
    pairs, report = build(cands, **args)
    assert [p["pair_id"] for p in pairs] == [p["pair_id"] for p in build(cands, **args)[0]]
    labels = [p["label"] for p in pairs]
    assert labels.count("ANSWERABLE") == 4 and labels.count("INSUFFICIENT_EVIDENCE") == 4
    assert not report["shortfall"]
    for p in pairs:
        assert set(TRAIN_FIELDS) <= set(p)
        assert p["source"] == "AIHUB" and p["contains_aihub"] is True and p["split"] == "TRAIN"
        assert p["label_source"] == "PUBLIC" and p["target"] == (p["label"] == "ANSWERABLE")
        assert p["evidence_id"] == p["pair_id"].replace("aihub:", "aihub-") + "-1"
        if p["label"] == "ANSWERABLE":
            assert p["anchor_text"] in p["evidence_text"]
    for lab in ("ANSWERABLE", "INSUFFICIENT_EVIDENCE"):
        titles = [p["aihub_title"] for p in pairs if p["label"] == lab]
        assert len(set(titles)) == len(titles)  # 문서당 라벨별 1개


def test_answer_cut_respects_cap():
    cands = candidates(groups(), Counter())
    pairs, _ = build(cands, count, 3, 2, 1, target_words=100, max_tokens=4, tokenize=bigram_tokens)
    ans = [p for p in pairs if p["label"] == "ANSWERABLE"]
    assert ans and all(count(p["evidence_text"]) <= 4 and p["anchor_text"] in p["evidence_text"] for p in ans)


def test_noanswer_picks_bm25_top_chunk():
    cands = candidates(groups(), Counter())
    pairs, _ = build(cands, count, 2, 1, 1, target_words=3, max_tokens=350, tokenize=bigram_tokens)
    neg = [p for p in pairs if p["label"] == "INSUFFICIENT_EVIDENCE"]
    assert neg and all(p["evidence_text"] == "시장은 매주 열립니다." for p in neg)
    assert all(p["bm25_chunk"] == 2 and p["bm25_chunks"] == 3 for p in neg)


def test_noanswer_without_overlap_is_dropped():
    cands = candidates(groups(question="날씨는 어떤가요?"), Counter())
    pairs, report = build(cands, count, 2, 1, 1, target_words=3, max_tokens=350, tokenize=bigram_tokens)
    assert not [p for p in pairs if p["label"] == "INSUFFICIENT_EVIDENCE"]
    assert report["shortfall"] == {"INSUFFICIENT_EVIDENCE": 2}
    assert sum(report["dropped"].values()) > 0


def test_candidates_counts_problems():
    ctx = "가상의 호수는 맑습니다. 호수의 깊이는 열 미터입니다."
    docs = [{"paragraphs": [{"context": ctx, "qas": [
        {"id": "a", "question": "깊이는?", "answers": [{"text": "열 미터", "answer_start": 0}]},  # 위치 보정
        {"id": "b", "question": "깊이는?", "is_impossible": True, "answers": []},  # 입력 종류와 다름
        {"id": "c", "question": "깊이는?", "answers": []},  # 정답 없음
        {"id": "a", "question": "중복?", "answers": [{"text": "호수", "answer_start": 4}]},  # id 중복
        {"question": "id 없음", "answers": [{"text": "맑습니다", "answer_start": ctx.index("맑습니다")}]},
    ]}]}]
    issues = Counter()
    cands = candidates([(False, "N:f", docs)], issues)
    assert [c["qid"] for c in cands] == ["a", "N:f-0-0-4"]
    assert cands[0]["answer"]["answer_start"] == ctx.index("열 미터")
    assert cands[0]["title"] == "N:f#0"
    assert issues == Counter({"answer_start 보정(정답이 지문에 한 번만 있음)": 1, "is_impossible이 입력 종류와 다름": 1,
                              "정답 있음인데 answers 없음": 1, "질문 id 중복": 1})


def test_same_context_in_both_files_used_once():
    ctx = "가상의 섬에는 등대가 있습니다. 등대는 하얀색입니다."
    n = [{"paragraphs": [{"context": ctx, "qas": [
        {"id": "n", "question": "등대 색은?", "answers": [{"text": "하얀색", "answer_start": ctx.index("하얀색")}]}]}]}]
    x = [{"paragraphs": [{"context": ctx, "qas": [{"id": "x", "question": "등대 높이는?", "answers": []}]}]}]
    cands = candidates([(False, "N:f", n), (True, "X:f", x)], Counter())
    pairs, _ = build(cands, count, 1, 1, 5, target_words=50, max_tokens=350, tokenize=bigram_tokens)
    assert len(pairs) == 1


def write_inputs(tmp_path):
    nd, xd = tmp_path / "normal", tmp_path / "noanswer"
    nd.mkdir()
    xd.mkdir()
    normal = {"data": normal_docs(), "가상키": "숨은내용"}
    (nd / "a.json").write_text(json.dumps(normal, ensure_ascii=False), encoding="utf-8")
    (xd / "b.json").write_text(json.dumps({"data": noanswer_docs()}, ensure_ascii=False), encoding="utf-8")
    (xd / "broken.json").write_text("{not json", encoding="utf-8")
    return nd, xd


CONTENT = ["마을", "사과", "특산물", "도시", "시장", "QID-", "가상 문서", "가상키", "숨은내용"]


def test_inspect_prints_structure_without_values(tmp_path):
    nd, xd = write_inputs(tmp_path)
    out = "\n".join(inspect([("normal", sorted(nd.glob("*.json"))), ("noanswer", sorted(xd.glob("*.json")))]))
    assert "$.data[].paragraphs[].qas[].is_impossible" in out and "True×18" in out and "False×18" in out
    assert "$.data[].paragraphs[].qas[].answers[].answer_start" in out
    assert "$.<?>" in out and "읽기 실패 1" in out
    assert not [w for w in CONTENT if w in out]


def test_main_prints_counts_only(tmp_path, monkeypatch, capsys):
    nd, xd = write_inputs(tmp_path)

    class FakeCounter:
        def __init__(self, name):
            pass

        @staticmethod
        def count(text):
            return len(text.split())

    monkeypatch.setattr(aihub_sample, "TokenCounter", FakeCounter)
    monkeypatch.setattr(sys, "argv", ["aihub_sample.py", "--normal", str(nd), "--noanswer", str(xd),
                                      "--out-root", str(tmp_path / "out"), "--n-per-label", "3", "--bm25", "bigram"])
    aihub_sample.main()
    out = capsys.readouterr().out
    assert "쌍 6개" in out and "파일 읽기 실패" in out
    assert not [w for w in CONTENT if w in out]
    out_dir = tmp_path / "out" / "sample-500"
    rows = [json.loads(line) for line in (out_dir / "pairs.jsonl").read_text("utf-8").splitlines()]
    assert len(rows) == 6 and all(r["contains_aihub"] for r in rows)
    meta = json.loads((out_dir / "meta.json").read_text("utf-8"))
    assert meta["bm25_tokenizer"] == "bigram" and "AI Hub" in meta["attribution"]
