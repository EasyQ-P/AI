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


def test_add_hard_negatives_and_separate_summary(tmp_path):
    from review_sample import add_hard_negatives

    train = train_rows()
    train += [row(f"ta{i}:hn1", "INSUFFICIENT_EVIDENCE", is_hard_negative=True) for i in range(8)]
    train += [row(f"da{i}:hn1", "INSUFFICIENT_EVIDENCE", "DOCUMENT", is_hard_negative=True) for i in range(2)]
    out = tmp_path / "rv"
    make(train, [], 0.1, 1, out)
    info = add_hard_negatives(train, 5, 1, out)
    assert info["rows"] == 5 and info["by_evidence_type"] == {"TRANSCRIPT": 4, "DOCUMENT": 1}
    with pytest.raises(ValueError):
        add_hard_negatives(train, 5, 1, out)  # 두 번 덧붙이지 않음
    path = out / "review.csv"
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["no"] for r in rows] == [str(i) for i in range(1, 11)]
    for r in rows:
        r["판정(O/X)"] = "X" if r["pair_id"].endswith(":hn1") and r["evidence_type"] == "DOCUMENT" else "O"
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = summary(out)
    assert s["overall"] == {"n": 5, "x": 0, "error_rate": 0.0}
    assert s["hard_negatives"]["overall"] == {"n": 5, "x": 1, "error_rate": 0.2}


def test_xlsx_roundtrip_summary(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from review_sample import to_xlsx

    train = train_rows() + [row("da0:hn1", "INSUFFICIENT_EVIDENCE", "DOCUMENT", is_hard_negative=True)]
    out = tmp_path / "rv"
    make(train, [], 0.1, 1, out)
    from review_sample import add_hard_negatives
    add_hard_negatives(train, 1, 1, out)
    path = to_xlsx(out, {"da0:hn1": "번역문"})
    with pytest.raises(ValueError):
        to_xlsx(out, {})  # 채운 엑셀 덮어쓰기 방지
    wb = openpyxl.load_workbook(path)
    ws = wb["검수"]
    head = [c.value for c in ws[1]]
    assert ws.max_row == 7 and "근거(참고 번역)" in head and wb.sheetnames == ["안내", "검수"]
    j, t, p = head.index("판정(O/X)") + 1, head.index("근거(참고 번역)") + 1, head.index("pair_id") + 1
    for r in range(2, ws.max_row + 1):
        hn = ws.cell(row=r, column=p).value == "da0:hn1"
        ws.cell(row=r, column=j, value="X" if hn else "O")
        if hn:
            assert ws.cell(row=r, column=t).value == "번역문"
    wb.save(path)
    s = summary(out)
    assert s["overall"] == {"n": 5, "x": 0, "error_rate": 0.0}
    assert s["hard_negatives"]["overall"] == {"n": 1, "x": 1, "error_rate": 1.0}


def test_fixes_actions_and_errors(tmp_path):
    from review_sample import fixes

    out = tmp_path / "rv"
    make(train_rows(), [], 0.1, 1, out)
    path = out / "review.csv"
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["판정(O/X)"] = "O"
    rows[1]["판정(O/X)"], rows[1]["맞는 라벨"] = "X", "제외"
    rows[2]["판정(O/X)"], rows[2]["맞는 라벨"] = "X", "INSUFFICIENT_EVIDENCE"

    def save():
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    save()
    got = fixes(out)
    assert [f["action"] for f in got] == ["ok", "drop", "relabel"]
    assert got[2]["label"] == "INSUFFICIENT_EVIDENCE"
    rows[3]["판정(O/X)"] = "X"  # 맞는 라벨 없음
    save()
    with pytest.raises(ValueError):
        fixes(out)
