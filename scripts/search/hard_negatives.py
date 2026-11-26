"""OCW 답변 가능 학습 쌍에 같은 강의의 어려운 오답 근거를 붙인다."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from retrieval.config import DEFAULT_CONFIG

try:
    from scripts.search.common import (
        build_searcher,
        count_distribution,
        output_directory,
        ratio,
        read_jsonl,
        write_json,
        write_jsonl,
    )
except ModuleNotFoundError:  # 직접 파일로 실행할 때
    from common import (  # type: ignore[no-redef]
        build_searcher,
        count_distribution,
        output_directory,
        ratio,
        read_jsonl,
        write_json,
        write_jsonl,
    )


def excluded_neighbor_ids(correct_id: str, details: dict[str, dict[str, Any]]) -> set[str]:
    excluded = {correct_id}
    correct = details.get(correct_id)
    if correct is None:
        return excluded
    lecture_id = correct["lecture_id"]
    if correct.get("evidence_type") == "TRANSCRIPT":
        chunk_index = correct.get("chunk_index")
        if isinstance(chunk_index, int):
            for doc_id, detail in details.items():
                if (
                    detail.get("evidence_type") == "TRANSCRIPT"
                    and detail.get("lecture_id") == lecture_id
                    and isinstance(detail.get("chunk_index"), int)
                    and abs(detail["chunk_index"] - chunk_index) <= 1
                ):
                    excluded.add(doc_id)
    else:
        page_no = correct.get("page_no")
        for doc_id, detail in details.items():
            if detail.get("lecture_id") == lecture_id and detail.get("page_no") == page_no and "text" in detail:
                excluded.add(doc_id)
    return excluded


def hard_negative_row(source: dict[str, Any], doc_id: str, rank: int,
                      details: dict[str, dict[str, Any]]) -> dict[str, Any]:
    detail = details[doc_id]
    output = dict(source)
    evidence_type = detail.get("evidence_type", "DOCUMENT")
    output.update(
        {
            "pair_id": f"{source['pair_id']}:hn{rank}",
            "evidence_id": doc_id,
            "evidence_text": detail["evidence_text_ko"] if evidence_type == "TRANSCRIPT" else detail["text"],
            "evidence_type": evidence_type,
            "evidence_lang": "ko" if evidence_type == "TRANSCRIPT" else "en",
            "page_no": detail.get("page_no"),
            "start_ms": detail.get("start_ms"),
            "end_ms": detail.get("end_ms"),
            "label": "INSUFFICIENT_EVIDENCE",
            "target": 0,
            "is_hard_negative": True,
            "gen_method": "HARD_NEGATIVE",
            "label_source": "HARD_NEGATIVE",
            "retrieval_config_version": DEFAULT_CONFIG.version,
        }
    )
    return output


def build_hard_negatives(pack: Path, name: str, embedder_kind: str = "fake", max_neg: int = 3) -> dict:
    if max_neg < 0:
        raise ValueError("max_neg must be non-negative")
    train = read_jsonl(pack / "dataset" / "train.jsonl")
    targets = [row for row in train if row.get("source") == "MIT_OCW" and row.get("label") == "ANSWERABLE"]
    searcher, details, embedder = build_searcher(pack, embedder_kind, DEFAULT_CONFIG)
    candidate_lists = searcher.search_many([(row["question_text"], row["lecture_id"]) for row in targets])

    output_rows: list[dict[str, Any]] = []
    recheck_rows: list[dict[str, Any]] = []
    attached_counts: list[int] = []
    evidence_types: Counter = Counter()
    correct_hits = 0
    for source, candidates in zip(targets, candidate_lists, strict=True):
        correct_id = source["evidence_id"]
        correct_hits += int(correct_id in candidates)
        excluded = excluded_neighbor_ids(correct_id, details)
        selected = [doc_id for doc_id in candidates if doc_id not in excluded][:max_neg]
        attached_counts.append(len(selected))
        for rank, doc_id in enumerate(selected, start=1):
            output = hard_negative_row(source, doc_id, rank, details)
            output_rows.append(output)
            evidence_types[output["evidence_type"]] += 1
            recheck_rows.append(
                {
                    "pair_id": output["pair_id"],
                    "question_text": output["question_text"],
                    "evidence_text": output["evidence_text"],
                }
            )

    output_dir = output_directory(name)
    write_jsonl(output_dir / "hard_negatives.jsonl", output_rows)
    write_jsonl(output_dir / "recheck.jsonl", recheck_rows)
    meta = {
        "retrieval_config": DEFAULT_CONFIG.to_dict(),
        "embedder": embedder.name,
        "max_neg": max_neg,
        "target_count": len(targets),
        "hard_negative_count": len(output_rows),
        "hard_negative_count_distribution": count_distribution(attached_counts),
        "evidence_type_distribution": dict(sorted(evidence_types.items())),
        "correct_evidence_candidate_rate": ratio(correct_hits, len(targets)),
    }
    write_json(output_dir / "hard_negatives_meta.json", meta)
    print(
        json.dumps(
            {
                "targets": len(targets),
                "hard_negatives": len(output_rows),
                "attached_counts": meta["hard_negative_count_distribution"],
                "evidence_types": meta["evidence_type_distribution"],
            },
            sort_keys=True,
        )
    )
    return meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("data/raw/easyq_ai2_search_pack"))
    parser.add_argument("--name", required=True, help="data/interim/search 아래 결과 디렉터리 이름")
    parser.add_argument("--embedder", choices=("fake", "gemini"), default="fake")
    parser.add_argument("--max-neg", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_hard_negatives(args.pack, args.name, args.embedder, args.max_neg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
