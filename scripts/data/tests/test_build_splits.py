from collections import Counter

import pytest
from build_splits import TRAIN_FIELDS, build, trim


def pair(pid: str, label: str, course: str | None = "6.006_S20", **kw) -> dict:
    p = {f: None for f in TRAIN_FIELDS}
    p.update(pair_id=pid, label=label, target=int(label == "ANSWERABLE"), course_id=course,
             lecture_id=f"{course}_L01", evidence_id=f"{pid}-e", evidence_text="근거", question_text="질문",
             source="MIT_OCW", question_source="SYNTHETIC", contains_aihub=False, split="TRAIN")
    p.update(kw)
    return p


def test_trim_counts_and_deterministic():
    pairs = [pair(f"{lab}{i}", lab) for i in range(10) for lab in ("ANSWERABLE", "OPINION")]
    a = trim(pairs, {"ANSWERABLE": 7, "OPINION": 4}, seed=1)
    assert [p["pair_id"] for p in a] == [p["pair_id"] for p in trim(pairs, {"ANSWERABLE": 7, "OPINION": 4}, seed=1)]
    assert sum(p["label"] == "ANSWERABLE" for p in a) == 7
    assert sum(p["label"] == "OPINION" for p in a) == 4
    with pytest.raises(ValueError):
        trim(pairs, {"ANSWERABLE": 11}, seed=1)


def test_trim_by_evidence_type():
    pairs = [pair(f"{t}{lab}{i}", lab, evidence_type=t)
             for t in ("TRANSCRIPT", "DOCUMENT") for lab in ("ANSWERABLE", "OPINION") for i in range(10)]
    counts = {"TRANSCRIPT": {"ANSWERABLE": 6, "OPINION": 5}, "DOCUMENT": {"ANSWERABLE": 3, "OPINION": 2}}
    got = trim(pairs, counts, seed=1)
    assert [p["pair_id"] for p in got] == [p["pair_id"] for p in trim(pairs, counts, seed=1)]
    c = Counter((p["evidence_type"], p["label"]) for p in got)
    assert c == Counter({("TRANSCRIPT", "ANSWERABLE"): 6, ("TRANSCRIPT", "OPINION"): 5,
                         ("DOCUMENT", "ANSWERABLE"): 3, ("DOCUMENT", "OPINION"): 2})
    with pytest.raises(ValueError):
        trim(pairs, {"DOCUMENT": {"ANSWERABLE": 11}}, seed=1)


def test_build_train_fields_and_eval_rows():
    ocw = [pair("o1", "ANSWERABLE", answer_hint="x"), pair("o2", "OPINION")]
    squad = [pair("s1", "INSUFFICIENT_EVIDENCE", course=None, source="SQUAD", squad_title="t")]
    val = [pair("v1", "ANSWERABLE", course="6.0001_F16", split="VALIDATION"),
           pair("v2", "OPINION", course="6.0001_F16", split="VALIDATION")]
    train, validation, meta = build(ocw, squad, val, None, 1)
    assert all(list(r) == TRAIN_FIELDS for r in train)
    assert meta["train"]["rows"] == 3 and meta["validation"]["escalate"] == 1
    assert validation[0]["gold_evidence_ids"] == ["v1-e"] and validation[1]["gold_evidence_ids"] == []
    assert validation[0]["candidates"] == [] and validation[0]["gold_in_candidates"] is None


def test_build_merges_aihub_and_guards_it():
    ocw = [pair("o1", "ANSWERABLE")]
    val = [pair("v1", "ANSWERABLE", course="6.0001_F16", split="VALIDATION")]
    aihub = [pair("a1", "INSUFFICIENT_EVIDENCE", course=None, source="AIHUB", contains_aihub=True)]
    train, _, meta = build(ocw, [], val, None, 1, aihub)
    assert meta["contains_aihub"] is True and meta["train"]["by_source"] == {"MIT_OCW": 1, "AIHUB": 1}
    assert build(ocw, [], val, None, 1)[2]["contains_aihub"] is False
    with pytest.raises(ValueError):  # AI Hub가 아닌 행을 --aihub로
        build(ocw, [], val, None, 1, [pair("a2", "ANSWERABLE", course=None)])
    with pytest.raises(ValueError):  # AI Hub 행을 --squad로
        build(ocw, aihub, val, None, 1)
    for bad in (dict(source="AIHUB", contains_aihub=True), dict(source="SQUAD")):  # 검증셋에 AI Hub · SQuAD
        with pytest.raises(ValueError):
            build(ocw, [], val + [pair("v2", "ANSWERABLE", course="6.0001_F16", split="VALIDATION", **bad)],
                  None, 1)


def test_build_rejects_course_in_both_splits():
    with pytest.raises(ValueError):
        build([pair("o1", "ANSWERABLE")], [], [pair("v1", "ANSWERABLE", split="VALIDATION")], None, 1)


def hn(base: str, rank: int, etype: str = "TRANSCRIPT", text: str = "오답 근거") -> dict:
    return pair(f"{base}:hn{rank}", "INSUFFICIENT_EVIDENCE", is_hard_negative=True, gen_method="HARD_NEGATIVE",
                label_source="HARD_NEGATIVE", evidence_type=etype, evidence_text=text)


def test_attach_hard_negatives_rank_max_and_recheck():
    from build_splits import attach_hard_negatives

    ocw = [pair("a1", "ANSWERABLE"), pair("a2", "ANSWERABLE"), pair("o1", "OPINION")]
    hns = [hn("a1", r) for r in (3, 1, 2)] + [hn("a2", 1, "DOCUMENT"), hn("gone", 1)]
    checked = {"a1:hn1": True, "a1:hn2": False, "a1:hn3": False, "a2:hn1": False}
    rows, stats = attach_hard_negatives(ocw, hns, max_per_question=2, checked=checked)
    assert [r["pair_id"] for r in rows] == ["a1:hn2", "a1:hn3", "a2:hn1"]  # hn1은 재확인에서 빠지고 다음 순위로
    assert all(r["label_source"] == "LLM" and r["split"] == "TRAIN" for r in rows)
    assert stats["dropped_recheck_answerable"] == 1 and stats["per_question"] == {"1": 1, "2": 1}
    assert stats["by_evidence_type"] == {"TRANSCRIPT": 2, "DOCUMENT": 1}
    # 재확인 결과를 주면 확인 안 한 오답(a2:hn1)은 쓰지 않는다
    rows2, stats2 = attach_hard_negatives(ocw, hns, 2, {"a1:hn2": False})
    assert [r["pair_id"] for r in rows2] == ["a1:hn2"] and stats2["skipped_unchecked"] == 3
    with pytest.raises(ValueError):
        attach_hard_negatives(ocw, [pair("a1:hn1", "ANSWERABLE")], 2, None)


def test_build_with_hard_negatives_meta():
    ocw = [pair("a1", "ANSWERABLE", evidence_type="TRANSCRIPT"), pair("a2", "ANSWERABLE", evidence_type="DOCUMENT")]
    val = [pair("v1", "ANSWERABLE", course="6.0001_F16", split="VALIDATION")]
    hns = [hn("a1", 1), hn("a2", 1, "DOCUMENT", "긴 교안 근거 문장")]
    train, _, meta = build(ocw, [], val, None, 1, None, hns, 2, None)
    assert len(train) == 4 and all(list(r) == TRAIN_FIELDS for r in train)
    assert meta["train"]["hard_negatives"]["rechecked"] is False
    lab = meta["train"]["ocw_evidence_by_label"]
    assert lab["ANSWERABLE"]["document_ratio"] == 0.5 and lab["INSUFFICIENT_EVIDENCE"]["document_ratio"] == 0.5


def test_apply_review_fixes():
    from build_splits import apply_review_fixes

    train = [pair("a1", "ANSWERABLE"), pair("a2", "ANSWERABLE"), pair("i1", "INSUFFICIENT_EVIDENCE"),
             pair("o1", "OPINION"), hn("a2", 1), hn("a1", 1)]
    fixes = [{"pair_id": "a1", "action": "relabel", "label": "INSUFFICIENT_EVIDENCE"},
             {"pair_id": "a2", "action": "drop", "label": None},
             {"pair_id": "i1", "action": "ok", "label": "INSUFFICIENT_EVIDENCE"}]
    out, stats = apply_review_fixes(train, fixes)
    by = {r["pair_id"]: r for r in out}
    assert set(by) == {"a1", "i1", "o1", "a1:hn1"}  # a2와 그 어려운 오답은 빠짐
    assert by["a1"]["label"] == "INSUFFICIENT_EVIDENCE" and by["a1"]["target"] == 0
    assert by["a1"]["label_source"] == by["i1"]["label_source"] == "LLM_HUMAN"
    assert by["o1"]["label_source"] is None  # 검수 안 한 행은 그대로
    assert stats == {"relabeled": 1, "dropped": 2, "confirmed": 1}
    with pytest.raises(ValueError):
        apply_review_fixes(train, [{"pair_id": "zzz", "action": "ok", "label": "OPINION"}])
