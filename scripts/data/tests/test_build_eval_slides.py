import pytest
from build_eval_slides import FIELDS, select


def row(course: str, lec: int, idx: int, key: str | None = None) -> dict:
    lecture_id = f"{course}_L{lec:02d}"
    return {
        "lecture_id": lecture_id, "course_id": course, "source_key": key or f"{lecture_id}_D{idx}_1",
        "page_no": idx, "chunk_index": idx, "text": "t", "token_count": 5, "split": "TEST",
    }


def test_select_filters_courses_orders_and_trims_fields():
    rows = [row("6.172_F18", 2, 1), row("6.006_S20", 1, 1), row("6.0001_F16", 1, 2), row("6.0001_F16", 1, 1)]
    out = select(rows, ["6.0001_F16", "6.172_F18"])
    assert [(r["lecture_id"], r["chunk_index"]) for r in out] == [
        ("6.0001_F16_L01", 1), ("6.0001_F16_L01", 2), ("6.172_F18_L02", 1)
    ]
    assert all(list(r) == FIELDS for r in out)


def test_select_rejects_duplicate_keys():
    with pytest.raises(ValueError):
        select([row("6.0001_F16", 1, 1, "k"), row("6.0001_F16", 1, 2, "k")], ["6.0001_F16"])
