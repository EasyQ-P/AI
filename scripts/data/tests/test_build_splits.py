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
