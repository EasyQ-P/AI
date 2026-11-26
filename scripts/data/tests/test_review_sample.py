import csv

import pytest
from review_sample import make, review_pool, sample, summary


def row(pid, label, etype="TRANSCRIPT", **kw):
    r = {"pair_id": pid, "label": label, "evidence_type": etype, "source": "MIT_OCW", "label_source": "LLM",
         "is_hard_negative": False, "question_text": "질문?", "evidence_text": "근거", "question_type": "개념"}
    r.update(kw)
    return r


def train_rows():
    rows = [row(f"t{lab[0]}{i}", lab) for lab in ("ANSWERABLE", "OPINION") for i in range(20)]
    rows += [row(f"d{i}", "ANSWERABLE", "DOCUMENT") for i in range(10)]
    rows += [row("hn1", "INSUFFICIENT_EVIDENCE", is_hard_negative=True),
             row("s1", "ANSWERABLE", source="SQUAD", label_source="PUBLIC")]
    return rows


def test_pool_and_stratified_sample():
    pool = review_pool(train_rows())
    assert {r["pair_id"] for r in pool} >= {"d0"} and not {"hn1", "s1"} & {r["pair_id"] for r in pool}
    got = sample(pool, 0.1, seed=1)
    assert len(got) == 5  # 2 + 2 + 1
    assert [r["pair_id"] for r in got] == [r["pair_id"] for r in sample(pool, 0.1, seed=1)]
    with pytest.raises(ValueError):
        review_pool([row("x", "ANSWERABLE", contains_aihub=True)])


def test_make_and_summary(tmp_path):
    out = tmp_path / "rv"
    meta = make(train_rows(), [], 0.1, 1, out)
    assert meta["rows"] == 5
    with pytest.raises(ValueError):
        make(train_rows(), [], 0.1, 1, out)  # 검수표 덮어쓰기 방지
    path = out / "review.csv"
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["판정(O/X)"], rows[1]["판정(O/X)"], rows[1]["맞는 라벨"] = "o", "X", "INSUFFICIENT_EVIDENCE"
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = summary(out)
    assert s["judged"] == 2 and s["overall"] == {"n": 2, "x": 1, "error_rate": 0.5}
    assert s["wrong"][0]["correct"] == "INSUFFICIENT_EVIDENCE"
