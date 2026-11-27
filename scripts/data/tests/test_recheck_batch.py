import json
import sys

import pytest
from recheck_batch import select, validate


def tr(pid, label="ANSWERABLE", source="MIT_OCW"):
    return {"pair_id": pid, "label": label, "source": source}


def hn(base, rank, etype="TRANSCRIPT"):
    return {"pair_id": f"{base}:hn{rank}", "evidence_type": etype, "question_text": "질문?", "evidence_text": "근거",
            "label": "INSUFFICIENT_EVIDENCE", "is_hard_negative": True}


def test_select_first_pass_and_refill():
    train = [tr("a1"), tr("a2"), tr("o1", "OPINION"), tr("s1", source="SQUAD")]
    hns = [hn("a1", r) for r in (1, 2, 3)] + [hn("a2", r) for r in (1, 2, 3)] + [hn("gone", 1)]
    first = [h["pair_id"] for h in select(train, hns, 2, {})]
    assert first == ["a1:hn1", "a1:hn2", "a2:hn1", "a2:hn2"]
    checked = {"a1:hn1": True, "a1:hn2": False, "a2:hn1": False, "a2:hn2": False}
    assert [h["pair_id"] for h in select(train, hns, 2, checked)] == ["a1:hn3"]  # 빠진 자리만 다음 순위로
    with pytest.raises(ValueError):
        select(train + [{"contains_aihub": True, "pair_id": "x", "label": "ANSWERABLE", "source": "AIHUB"}],
               hns, 2, {})


def test_validate_outputs():
    inputs = [{"pair_id": p} for p in ("a:hn1", "a:hn2", "b:hn1")]
    outputs = [{"pair_id": "a:hn1", "answerable": False, "reason": "없음"}, {"pair_id": "a:hn1", "answerable": True},
               {"pair_id": "a:hn2", "answerable": "no"}, {"pair_id": "zzz", "answerable": False}]
    result, problems = validate(inputs, outputs)
    assert result == [{"pair_id": "a:hn1", "answerable": False, "reason": "없음"}]
    assert problems["missing"] == ["b:hn1"] and set(problems["errors"]) == {"a:hn1", "a:hn2", "zzz"}


def test_prepare_ingest_end_to_end(tmp_path, monkeypatch):
    import recheck_batch
    from recheck_batch import read_jsonl, write_jsonl

    write_jsonl(tmp_path / "train.jsonl", [tr("a1"), tr("a2")])
    write_jsonl(tmp_path / "hn.jsonl", [hn("a1", r) for r in (1, 2)] + [hn("a2", 1, "DOCUMENT")])
    root = tmp_path / "rc"
    monkeypatch.setattr(sys, "argv", ["x", "--root", str(root), "prepare", "--name", "b1", "--train",
                                      str(tmp_path / "train.jsonl"), "--hard-negatives", str(tmp_path / "hn.jsonl"),
                                      "--part-size", "2"])
    recheck_batch.main()
    b = root / "b1"
    assert len(read_jsonl(b / "input.jsonl")) == 3 and len(list((b / "parts").glob("in_*.jsonl"))) == 2
    assert "hn_recheck_v1" in (b / "TASK.md").read_text(encoding="utf-8")
    write_jsonl(b / "parts" / "out_01.jsonl", [{"pair_id": "a1:hn1", "answerable": True, "reason": "답 있음"},
                                               {"pair_id": "a1:hn2", "answerable": False, "reason": "없음"}])
    write_jsonl(b / "parts" / "out_02.jsonl", [{"pair_id": "a2:hn1", "answerable": False, "reason": "없음"}])
    monkeypatch.setattr(sys, "argv", ["x", "--root", str(root), "ingest", "--name", "b1", "--model", "m"])
    recheck_batch.main()
    meta = json.loads((b / "meta.json").read_text(encoding="utf-8"))
    assert meta["results"] == 3 and meta["answerable"] == 1 and meta["missing"] == [] and meta["errors"] == {}
