import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import retrieval.keyword as keyword_module
from scripts.search.build_val_candidates import build_candidates
from scripts.search.common import load_search_documents
from scripts.search.hard_negatives import build_hard_negatives, excluded_neighbor_ids


class WhitespaceKiwi:
    def tokenize(self, text):
        return [SimpleNamespace(form=part, tag="SL") for part in text.split()]


@pytest.fixture(autouse=True)
def fake_kiwi(monkeypatch):
    monkeypatch.setattr(keyword_module, "_KIWI", WhitespaceKiwi())


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_pack(root: Path) -> Path:
    pack = root / "pack"
    transcript_rows = [
        {
            "evidence_id": f"L_T{index:04d}",
            "lecture_id": "L",
            "course_id": "C",
            "evidence_type": "TRANSCRIPT",
            "evidence_text": f"english {index}",
            "evidence_text_ko": f"공통 발화 {index}",
            "chunk_index": index - 1,
            "start_ms": index * 1000,
            "end_ms": (index + 1) * 1000,
            "contains_aihub": False,
        }
        for index in range(1, 6)
    ]
    write_jsonl(pack / "index/transcripts/train.jsonl", transcript_rows)
    slide_rows = [
        {
            "source_key": "L_D1_1",
            "lecture_id": "L",
            "course_id": "C",
            "page_no": 1,
            "chunk_index": 0,
            "text": "common document one",
            "contains_aihub": False,
        },
        {
            "source_key": "L_D1_2",
            "lecture_id": "L",
            "course_id": "C",
            "page_no": 1,
            "chunk_index": 1,
            "text": "common document two",
            "contains_aihub": False,
        },
        {
            "source_key": "L_D2_1",
            "lecture_id": "L",
            "course_id": "C",
            "page_no": 2,
            "chunk_index": 2,
            "text": "common document three",
            "contains_aihub": False,
        },
    ]
    write_jsonl(pack / "index/slides-v4/course.jsonl", slide_rows)
    write_jsonl(
        pack / "index/slides-v4/6.172_F18.jsonl",
        [
            {
                "source_key": "EXCLUDED_D1_1",
                "lecture_id": "EXCLUDED",
                "page_no": 1,
                "chunk_index": 0,
                "text": "must not be indexed",
                "contains_aihub": False,
            }
        ],
    )
    return pack


def test_build_val_candidates_writes_ranked_ids_and_meta(tmp_path, monkeypatch) -> None:
    pack = make_pack(tmp_path)
    validation = [
        {
            "eval_question_id": "eval-1",
            "lecture_id": "L",
            "question_text": "공통 질문",
            "candidates": [],
            "synth_evidence_id": "L_T0001",
            "contains_aihub": False,
        }
    ]
    write_jsonl(pack / "dataset/validation.jsonl", validation)
    monkeypatch.chdir(tmp_path)

    meta = build_candidates(pack, "validation-run", "fake")

    output_path = tmp_path / "data/interim/search/validation-run/validation.jsonl"
    output = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert output["eval_question_id"] == "eval-1"
    assert output["retrieval_config_version"] == "rc-v1"
    assert output["candidates"]
    assert all(isinstance(candidate, str) for candidate in output["candidates"])
    assert "EXCLUDED_D1_1" not in output["candidates"]
    assert (tmp_path / "data/interim/search/validation-run/validation_meta.json").exists()
    assert meta["question_count"] == 1
    assert sum(meta["candidate_count_distribution"].values()) == 1
    assert set(meta["synth_evidence_hit_rate"]) == {"all", "top_5", "top_10"}


def test_build_hard_negatives_writes_training_rows_and_excludes_transcript_neighbors(tmp_path, monkeypatch) -> None:
    pack = make_pack(tmp_path)
    source = {
        "pair_id": "pair-1",
        "course_id": "C",
        "lecture_id": "L",
        "question_text": "공통 질문",
        "evidence_text": "원래 근거",
        "evidence_type": "TRANSCRIPT",
        "evidence_id": "L_T0002",
        "page_no": None,
        "start_ms": 2000,
        "end_ms": 3000,
        "label": "ANSWERABLE",
        "target": 1,
        "source": "MIT_OCW",
        "gen_method": "SYNTHETIC",
        "is_hard_negative": False,
        "contains_aihub": False,
        "evidence_lang": "ko",
    }
    write_jsonl(pack / "dataset/train.jsonl", [source])
    monkeypatch.chdir(tmp_path)

    meta = build_hard_negatives(pack, "hard-run", "fake", max_neg=3)

    output_dir = tmp_path / "data/interim/search/hard-run"
    rows = [json.loads(line) for line in (output_dir / "hard_negatives.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    assert len(rows) <= 3
    assert {row["evidence_id"] for row in rows}.isdisjoint({"L_T0001", "L_T0002", "L_T0003"})
    assert [row["pair_id"] for row in rows] == [f"pair-1:hn{index}" for index in range(1, len(rows) + 1)]
    for row in rows:
        assert row["question_text"] == source["question_text"]
        assert row["label"] == "INSUFFICIENT_EVIDENCE"
        assert row["target"] == 0
        assert row["is_hard_negative"] is True
        assert row["gen_method"] == "HARD_NEGATIVE"
        assert row["label_source"] == "HARD_NEGATIVE"
        assert row["retrieval_config_version"] == "rc-v1"
        assert row["evidence_lang"] == ("ko" if row["evidence_type"] == "TRANSCRIPT" else "en")

    recheck = [json.loads(line) for line in (output_dir / "recheck.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(set(row) == {"pair_id", "question_text", "evidence_text"} for row in recheck)
    assert (output_dir / "hard_negatives_meta.json").exists()
    assert meta["target_count"] == 1
    assert meta["hard_negative_count"] == len(rows)
    assert sum(meta["evidence_type_distribution"].values()) == len(rows)


def test_document_neighbors_on_same_page_are_excluded(tmp_path) -> None:
    pack = make_pack(tmp_path)
    _, details = load_search_documents(pack)

    excluded = excluded_neighbor_ids("L_D1_1", details)

    assert {"L_D1_1", "L_D1_2"} <= excluded
    assert "L_D2_1" not in excluded


@pytest.mark.parametrize("builder,dataset_name", [(build_candidates, "validation"), (build_hard_negatives, "train")])
def test_scripts_reject_ai_hub_rows(tmp_path, monkeypatch, builder, dataset_name) -> None:
    pack = make_pack(tmp_path)
    write_jsonl(
        pack / f"dataset/{dataset_name}.jsonl",
        [
            {
                "question_text": "sensitive",
                "contains_aihub": True,
            }
        ],
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="AI Hub data is not allowed"):
        builder(pack, "rejected", "fake")
    assert not (tmp_path / "data/interim/search/rejected").exists()


@pytest.mark.parametrize("row,blocked", [
    ({"question_text": "q"}, False),                       # 필드 없음(검증 · 시험셋 · 교안 조각)
    ({"contains_aihub": False}, False),
    ({"contains_aihub": "false"}, False),
    ({"contains_aihub": True}, True),
    ({"contains_aihub": 1}, True),
    ({"contains_aihub": "true"}, True),
    ({"contains_aihub": "yes"}, True),                     # 모르는 값은 막는다
    ({"source": "AIHUB"}, True),
    ({"source": "aihub", "contains_aihub": False}, True),
    (["not", "a", "dict"], True),
])
def test_is_aihub_row_blocks_every_truthy_form(row, blocked) -> None:
    from scripts.search.common import is_aihub_row

    assert is_aihub_row(row) is blocked
