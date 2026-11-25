from collections import Counter

from synth_batch import (
    OPINION_CUE_RE,
    TOPIC_TYPES,
    assign_target_types,
    has_logistics,
    overlap,
    overlap_warnings,
    quality_report,
    select_chunks,
    to_pairs,
    validate_output,
)


def chunk(eid: str) -> dict:
    lecture = eid.rsplit("_", 1)[0]
    return {"evidence_id": eid, "lecture_id": lecture, "course_id": "6.006_S20", "evidence_text": "x"}


def good_row(**over) -> dict:
    row = {
        "evidence_id": "6.006_S20_L03_T0001",
        "ko_text": "정렬된 배열에서는 이진 탐색으로 찾을 수 있어요.",
        "content": True,
        "skip": False,
        "questions": [
            {"gen_method": "ANSWERABLE", "question_text": "정렬된 배열은 어떻게 찾아요?", "question_type": "방법"},
            {"gen_method": "OUT_OF_SCOPE", "question_text": "이진 탐색은 몇 번 비교해요?", "question_type": "개념"},
            {"gen_method": "OPINION", "question_text": "교수님은 이진 탐색 좋아하세요?", "question_type": "의견"},
        ],
    }
    row.update(over)
    return row


def test_select_chunks_is_deterministic_and_lecture_only():
    chunks = [chunk(f"6.006_S20_L0{i}_T000{j}") for i in range(1, 5) for j in range(1, 4)]
    chunks.append(chunk("6.006_S20_PS1_T0001"))
    a = select_chunks(chunks, 5, seed=7, exclude_lectures={"6.006_S20_L01"})
    b = select_chunks(chunks, 5, seed=7, exclude_lectures={"6.006_S20_L01"})
    assert a == b and len(a) == 5
    assert all("_L01_" not in c["evidence_id"] and "_PS" not in c["evidence_id"] for c in a)


def test_assign_target_types_balanced_and_different_per_chunk():
    targets = assign_target_types(["We sort the array."] * 30, seed=1)
    assert Counter(t["ANSWERABLE"] for t in targets) == {t: 6 for t in TOPIC_TYPES}
    assert Counter(t["OUT_OF_SCOPE"] for t in targets) == {t: 6 for t in TOPIC_TYPES}
    assert all(t["ANSWERABLE"] != t["OUT_OF_SCOPE"] and t["OPINION"] == "의견" for t in targets)
    assert assign_target_types(["We sort the array."] * 30, seed=1) == targets


def test_logistics_type_only_on_logistics_chunks_and_split_between_labels():
    texts = ["We sort the array."] * 10 + [
        "This will be on the exam.",
        "See you next lecture.",
        "Problem set 3 is out.",
    ]
    targets = assign_target_types(texts, seed=3)
    assert all("운영" not in (t["ANSWERABLE"], t["OUT_OF_SCOPE"]) for t in targets[:10])
    ops = targets[10:]
    assert [t["ANSWERABLE"] == "운영" for t in ops] == [True, False, True]
    assert [t["OUT_OF_SCOPE"] == "운영" for t in ops] == [False, True, False]


def test_has_logistics():
    assert has_logistics("Your homework is due Friday.")
    assert has_logistics("we'll see that next week")
    assert not has_logistics("The final answer is n squared.")


def test_has_logistics_ignores_review_phrases_loops_and_variable_names():
    assert not has_logistics("As we saw last time, the next time through the loop adds an a.")
    assert not has_logistics("delete the entry from the dictionary grades, then print grades")


def test_overlap_warnings_flag_label_shortcuts():
    pairs = to_pairs(good_row(), chunk("6.006_S20_L03_T0001"), "b1")
    for p in pairs:
        p["evidence_text"] = "정렬된 배열에서는 이진 탐색으로 찾을 수 있어요"
    pairs[0]["question_text"] = "정렬된 배열에서는 이진 탐색으로 찾을 수 있어요?"  # 답변 가능: 청크 문장 그대로
    pairs[1]["question_text"] = "해시 테이블은 왜 느려요?"  # 근거 부족: 청크 단어 없음
    w = overlap_warnings(pairs)
    assert w["answerable_overlap_above"]["pair_ids"] == [pairs[0]["pair_id"]]
    assert w["out_of_scope_overlap_below"]["pair_ids"] == [pairs[1]["pair_id"]]


def test_opinion_cue_re_catches_comparative_wording():
    for text in ("for가 while보다 더 나아요?", "이 방법이 더 나은가요?", "이렇게 해도 괜찮을까요?", "교수님은 어때요?"):
        assert OPINION_CUE_RE.search(text), text
    assert not OPINION_CUE_RE.search("리스트는 어떻게 만들어요?")


def test_quality_report_opinion_cue_rate():
    ans = to_pairs(good_row(), chunk("6.006_S20_L03_T0001"), "b1")
    report = quality_report(ans)["by_gen_method"]
    assert report["OPINION"]["opinion_cue_rate"] == 1.0  # "교수님은 …"
    assert report["ANSWERABLE"]["opinion_cue_rate"] == 0.0


def test_validate_output():
    assert validate_output(good_row()) == []
    bad = good_row(questions=good_row()["questions"][:2])
    assert any("gen_method" in e for e in validate_output(bad))
    long_q = good_row()
    long_q["questions"][2]["question_text"] = "교수님은 " + "아주 " * 20 + "좋아하세요?"
    assert validate_output(long_q) == []
    assert any("질문 길이" in e for e in validate_output(long_q, strict_len=True))
    assert validate_output(good_row(skip=True, questions=[])) == []


def test_to_pairs_labels_and_targets():
    row = good_row()
    pairs = to_pairs(row, chunk(row["evidence_id"]), "b1")
    assert [(p["gen_method"], p["label"], p["target"]) for p in pairs] == [
        ("ANSWERABLE", "ANSWERABLE", 1),
        ("OUT_OF_SCOPE", "INSUFFICIENT_EVIDENCE", 0),
        ("OPINION", "OPINION", 0),
    ]
    assert {p["split"] for p in pairs} == {"TRAIN"}
    assert all(p["evidence_lang"] == "ko" and not p["contains_aihub"] for p in pairs)


def test_overlap_and_quality_report():
    assert overlap("정렬된 배열", "정렬된 배열에서는") == 1.0
    assert overlap("해시 함수", "정렬된 배열") == 0.0
    report = quality_report(to_pairs(good_row(), chunk("6.006_S20_L03_T0001"), "b1"))
    assert set(report["by_gen_method"]) == {"ANSWERABLE", "OUT_OF_SCOPE", "OPINION"}
    assert report["question_type"]["의견"] == 1


def test_lecture_chunks_takes_whole_lectures_across_courses(tmp_path):
    from synth_batch import lecture_chunks, write_jsonl

    def chunk(lid, i):
        return {"evidence_id": f"{lid}_T{i:04d}", "lecture_id": lid, "course_id": lid.rsplit("_", 1)[0]}

    write_jsonl(tmp_path / "A_S1.jsonl", [chunk("A_S1_L01", i) for i in (1, 2)] + [chunk("A_S1_L02", 1)])
    write_jsonl(tmp_path / "B_F2.jsonl", [chunk("B_F2_L05", 1)])
    got = lecture_chunks(tmp_path, ["A_S1_L01", "B_F2_L05"])
    assert [c["evidence_id"] for c in got] == ["A_S1_L01_T0001", "A_S1_L01_T0002", "B_F2_L05_T0001"]


# ---------------------------------------------------------------- 교안 조각(slides) 모드 (2026-11-25 B안)

def slide(lid: str, page: int, part: int = 1, text: str = "Binary search halves the range each step.") -> dict:
    return {"lecture_id": lid, "source_key": f"{lid}_D{page}_{part}", "page_no": page, "chunk_index": page,
            "text": text, "course_id": lid.rsplit("_", 1)[0], "split": "TRAIN", "token_count": 10}


def slide_src() -> dict:
    from synth_batch import slide_rows

    return slide_rows([slide("6.006_S20_L03", 4)])[0]


def test_slide_rows_use_source_key_and_document():
    src = slide_src()
    assert src["evidence_id"] == "6.006_S20_L03_D4_1" and src["course_id"] == "6.006_S20"
    assert src["evidence_type"] == "DOCUMENT" and src["page_no"] == 4


def test_validate_output_slides_without_ko_text():
    row = good_row(evidence_id="6.006_S20_L03_D4_1")
    del row["ko_text"]
    assert any("ko_text" in e for e in validate_output(row))
    assert validate_output(row, need_ko_text=False) == []


def test_to_pairs_slides_keep_english_original():
    row = good_row(evidence_id="6.006_S20_L03_D4_1")
    del row["ko_text"]
    pairs = to_pairs(row, slide_src(), "s1")
    assert all(p["evidence_text"] == "Binary search halves the range each step." for p in pairs)
    assert all(p["evidence_type"] == "DOCUMENT" and p["page_no"] == 4 and p["evidence_lang"] == "en" for p in pairs)
    assert all(p["question_lang"] == "ko" and p["split"] == "TRAIN" for p in pairs)
    # 영어 근거는 단어 겹침 확인선에서 뺀다(한국어 질문과 겹칠 수 없음)
    w = overlap_warnings(pairs)
    assert w["out_of_scope_overlap_below"]["pair_ids"] == [] and w["answerable_overlap_above"]["pair_ids"] == []


def test_prepare_and_ingest_slides_end_to_end(tmp_path, monkeypatch):
    import json
    import sys

    import synth_batch
    from synth_batch import read_jsonl, write_jsonl

    sdir = tmp_path / "slides"
    sdir.mkdir()
    write_jsonl(sdir / "6.006_S20.jsonl", [slide("6.006_S20_L01", p) for p in range(1, 6)])
    write_jsonl(sdir / "6.034_F10.jsonl", [slide("6.034_F10_L02", p) for p in range(1, 6)])
    root = tmp_path / "synth"
    argv = ["synth_batch.py", "--root", str(root), "prepare", "--source", "slides", "--batch", "s1",
            "--courses", "6.006_S20", "6.034_F10", "--slides", str(sdir), "--n", "4", "--seed", "7"]
    monkeypatch.setattr(sys, "argv", argv)
    synth_batch.main()
    batch = root / "s1"
    rows = read_jsonl(batch / "input.jsonl")
    assert len(rows) == 4 and all(r["evidence_type"] == "DOCUMENT" and "target_types" in r for r in rows)
    monkeypatch.setattr(sys, "argv", argv)
    synth_batch.main()
    assert [r["evidence_id"] for r in read_jsonl(batch / "input.jsonl")] == [r["evidence_id"] for r in rows]
    meta = json.loads((batch / "meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "slides" and meta["prompts"] == {"rewrite": None, "questions": "question_synth_slides_v1"}
    assert "번역하지 않는다" in (batch / "TASK.md").read_text(encoding="utf-8")

    outs = []
    for i, r in enumerate(rows):
        row = good_row(evidence_id=r["evidence_id"])
        del row["ko_text"]
        if i == 3:
            row.update(content=False, skip=True, questions=[])
        outs.append(row)
    write_jsonl(batch / "output.jsonl", outs)
    monkeypatch.setattr(sys, "argv", ["synth_batch.py", "--root", str(root), "ingest", "--batch", "s1", "--model", "m"])
    synth_batch.main()
    pairs = read_jsonl(batch / "pairs.jsonl")
    assert len(pairs) == 9 and all(p["evidence_type"] == "DOCUMENT" for p in pairs)
    meta = json.loads((batch / "meta.json").read_text(encoding="utf-8"))
    assert meta["errors"] == {} and len(meta["skipped_no_question"]) == 1


def test_balanced_select_equal_and_redistributes():
    from synth_batch import balanced_select, slide_rows

    rows = slide_rows([slide("A_S1_L01", p) for p in range(1, 4)]          # 3조각뿐
                      + [slide("B_F2_L01", p) for p in range(1, 21)]
                      + [slide("C_S3_L01", p) for p in range(1, 31)])
    got = balanced_select(rows, 20, seed=3, exclude_lectures=set())
    c = Counter(r["course_id"] for r in got)
    assert c == Counter({"A_S1": 3, "B_F2": 8, "C_S3": 9})
    assert [r["evidence_id"] for r in got] == [r["evidence_id"] for r in balanced_select(rows, 20, 3, set())]
    assert Counter(r["course_id"] for r in balanced_select(rows, 9, 3, set())) == Counter(
        {"A_S1": 3, "B_F2": 3, "C_S3": 3})
