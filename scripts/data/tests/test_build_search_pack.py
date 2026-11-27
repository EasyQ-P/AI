import json

import pytest
from build_search_pack import build_pack, read_jsonl, write_jsonl


def make_inputs(tmp_path):
    train = [
        {"pair_id": "t1", "source": "MIT_OCW", "label": "ANSWERABLE", "evidence_type": "DOCUMENT",
         "course_id": "6.006_S20", "lecture_id": "6.006_S20_L05"},
        {"pair_id": "t2", "source": "MIT_OCW", "label": "ANSWERABLE", "evidence_type": "TRANSCRIPT",
         "course_id": "6.006_S20", "lecture_id": "6.006_S20_L07"},
        {"pair_id": "t3", "source": "MIT_OCW", "label": "OPINION", "evidence_type": "DOCUMENT",
         "course_id": "6.006_S20", "lecture_id": "6.006_S20_L05"},
        {"pair_id": "s1", "source": "SQUAD", "label": "ANSWERABLE", "evidence_type": "DOCUMENT", "course_id": None},
    ]
    chunks = tmp_path / "chunks"
    write_jsonl(chunks / "6.006_S20.jsonl", [
        {"evidence_id": f"6.006_S20_L07_T000{i}", "lecture_id": "6.006_S20_L07", "course_id": "6.006_S20",
         "evidence_text": f"english {i}"} for i in (1, 2)
    ] + [{"evidence_id": "6.006_S20_L05_T0001", "lecture_id": "6.006_S20_L05", "course_id": "6.006_S20",
          "evidence_text": "no ko"}])
    synth = tmp_path / "synth"
    write_jsonl(synth / "output.jsonl", [{"evidence_id": f"6.006_S20_L07_T000{i}", "ko_text": f"한국어 {i}"}
                                         for i in (1, 2)])
    slides = tmp_path / "slides"
    write_jsonl(slides / "6.006_S20.jsonl", [{"lecture_id": "6.006_S20_L05", "source_key": "6.006_S20_L05_D1_1",
                                              "page_no": 1, "chunk_index": 1, "text": "slide"}])
    return train, synth, chunks, slides


def test_build_pack_document_targets_and_index(tmp_path):
    train, synth, chunks, slides = make_inputs(tmp_path)
    out = tmp_path / "pack"
    meta = build_pack(train, {"DOCUMENT"}, [synth], chunks, slides, out)
    assert [r["pair_id"] for r in read_jsonl(out / "dataset" / "train.jsonl")] == ["t1"]
    t = read_jsonl(out / "index" / "transcripts" / "6.006_S20.jsonl")
    assert [(r["evidence_id"], r["chunk_index"], r["evidence_type"], r["evidence_text_ko"]) for r in t] == [
        ("6.006_S20_L07_T0001", 1, "TRANSCRIPT", "한국어 1"), ("6.006_S20_L07_T0002", 2, "TRANSCRIPT", "한국어 2")]
    assert len(read_jsonl(out / "index" / "slides-v4" / "6.006_S20.jsonl")) == 1
    assert meta["targets"] == 1 and meta["targets_without_transcript_index"] == 1
    # 다시 만들면 덮어쓴다(이 스크립트가 만든 묶음)
    assert build_pack(train, None, [synth], chunks, slides, out)["targets"] == 2


def test_build_pack_refuses_foreign_dir_and_aihub(tmp_path):
    train, synth, chunks, slides = make_inputs(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "x.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        build_pack(train, None, [synth], chunks, slides, foreign)
    assert (foreign / "x.txt").exists()
    with pytest.raises(ValueError):
        build_pack(train + [{"contains_aihub": True, "source": "AIHUB", "label": "ANSWERABLE"}], None, [synth],
                   chunks, slides, tmp_path / "p2")
    assert json  # noqa: B018
