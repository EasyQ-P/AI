import json
from collections import Counter

from sample_pairs import assign_labels, main

LABELS = ("ANSWERABLE", "INSUFFICIENT_EVIDENCE", "OPINION")


def write_pairs(path, lectures: dict[str, int]) -> None:
    rows = []
    for lec, n in lectures.items():
        for i in range(1, n + 1):
            eid = f"{lec}_T{i:04d}"
            for lab in LABELS:
                rows.append({"pair_id": f"b:{eid}:{lab}", "evidence_id": eid, "lecture_id": lec, "label": lab})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def run(tmp_path, monkeypatch, seed: int, counts: dict) -> list[dict]:
    monkeypatch.setattr(
        "sys.argv",
        ["sample_pairs.py", "--root", str(tmp_path), "--batch", "b", "--name", "s",
         "--seed", str(seed), "--counts", json.dumps(counts)],
    )
    main()
    out = tmp_path / "b" / "s" / "pairs.jsonl"
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def test_counts_one_per_chunk_and_deterministic(tmp_path, monkeypatch):
    (tmp_path / "b").mkdir()
    write_pairs(tmp_path / "b" / "pairs.jsonl", {"C_L01": 40, "C_L02": 60, "C_L03": 100})
    counts = {"ANSWERABLE": 21, "INSUFFICIENT_EVIDENCE": 21, "OPINION": 18}
    a = run(tmp_path, monkeypatch, 7, counts)
    b = run(tmp_path, monkeypatch, 7, counts)
    assert [p["pair_id"] for p in a] == [p["pair_id"] for p in b]
    assert Counter(p["label"] for p in a) == counts
    assert len({p["evidence_id"] for p in a}) == len(a) == 60
    # 강의 비율(40:60:100)대로 나뉜다
    assert Counter(p["lecture_id"] for p in a) == {"C_L01": 12, "C_L02": 18, "C_L03": 30}
    c = run(tmp_path, monkeypatch, 8, counts)
    assert [p["pair_id"] for p in a] != [p["pair_id"] for p in c]


def test_assign_labels_fills_total_when_rounding_short():
    import random

    eids = [f"C_L0{k}_T{i:04d}" for k in (1, 2, 3) for i in range(1, 4)]  # 강의 3개 × 3청크
    got = assign_labels(eids, {"ANSWERABLE": 4, "OPINION": 3}, random.Random(1))
    assert len(got) == 7
    assert Counter(got.values()) == {"ANSWERABLE": 4, "OPINION": 3}
