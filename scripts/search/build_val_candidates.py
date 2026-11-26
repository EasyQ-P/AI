"""검증 질문마다 같은 강의의 하이브리드 검색 후보를 저장한다."""

import argparse
import json
from pathlib import Path

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


def build_candidates(pack: Path, name: str, embedder_kind: str = "fake") -> dict:
    validation = read_jsonl(pack / "dataset" / "validation.jsonl")
    searcher, _, embedder = build_searcher(pack, embedder_kind, DEFAULT_CONFIG)
    queries = [(row["question_text"], row["lecture_id"]) for row in validation]
    candidate_lists = searcher.search_many(queries)

    output_rows = []
    hit_counts = {"all": 0, "top_5": 0, "top_10": 0}
    for row, candidates in zip(validation, candidate_lists, strict=True):
        output = dict(row)
        output["candidates"] = candidates
        output["retrieval_config_version"] = DEFAULT_CONFIG.version
        output_rows.append(output)
        synth_id = row.get("synth_evidence_id")
        hit_counts["all"] += int(synth_id in candidates)
        hit_counts["top_5"] += int(synth_id in candidates[:5])
        hit_counts["top_10"] += int(synth_id in candidates[:10])

    output_dir = output_directory(name)
    write_jsonl(output_dir / "validation.jsonl", output_rows)
    total = len(validation)
    meta = {
        "retrieval_config": DEFAULT_CONFIG.to_dict(),
        "embedder": embedder.name,
        "question_count": total,
        "candidate_count_distribution": count_distribution(len(candidates) for candidates in candidate_lists),
        "synth_evidence_hit_rate": {
            "all": ratio(hit_counts["all"], total),
            "top_5": ratio(hit_counts["top_5"], total),
            "top_10": ratio(hit_counts["top_10"], total),
        },
    }
    write_json(output_dir / "validation_meta.json", meta)
    print(json.dumps({"questions": total, "candidate_counts": meta["candidate_count_distribution"]}, sort_keys=True))
    return meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("data/raw/easyq_ai2_search_pack"))
    parser.add_argument("--name", required=True, help="data/interim/search 아래 결과 디렉터리 이름")
    parser.add_argument("--embedder", choices=("fake", "gemini"), default="fake")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_candidates(args.pack, args.name, args.embedder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
