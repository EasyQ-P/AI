"""검색 데이터 구축 스크립트의 공통 입출력과 색인 준비."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from retrieval.config import DEFAULT_CONFIG, RetrievalConfig
from retrieval.embedding import CachedEmbedder, Embedder, FakeEmbedder, GeminiEmbedder
from retrieval.search import HybridSearcher, SearchDoc

INTERIM_ROOT = Path("data/interim/search")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL을 읽되 AI Hub 행을 발견하면 내용을 다루기 전에 중단한다."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if is_aihub_row(row):
                raise RuntimeError(f"AI Hub data is not allowed: {path}:{line_number}")
            rows.append(row)
    return rows


def is_aihub_row(row: Any) -> bool:
    """AI Hub 행인지 판단한다(외부 임베딩 API로 보내기 전 차단용, 설계서 3.1.3).

    `contains_aihub`가 없는 행은 통과시킨다. 검증 · 시험셋과 교안 조각 파일에는 이 필드가 원래 없다(3.3.3).
    값이 있으면 True뿐 아니라 1 · "true" 같은 표기도 AI Hub로 본다. `source == "AIHUB"`도 막는다.
    행이 객체가 아니면 내용을 알 수 없으므로 막는다.
    """
    if not isinstance(row, dict):
        return True
    flag = row.get("contains_aihub")
    if flag is not None and flag is not False:
        if not (isinstance(flag, (int, str)) and str(flag).strip().lower() in ("0", "false", "")):
            return True
    return str(row.get("source", "")).strip().upper() == "AIHUB"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as destination:
        json.dump(value, destination, ensure_ascii=False, indent=2, sort_keys=True)
        destination.write("\n")


def output_directory(name: str) -> Path:
    if not name or Path(name).name != name:
        raise ValueError("name must be a single non-empty path component")
    return INTERIM_ROOT / name


def make_embedder(kind: str, config: RetrievalConfig = DEFAULT_CONFIG) -> Embedder:
    if kind == "fake":
        return FakeEmbedder()
    if kind == "gemini":
        inner = GeminiEmbedder(model=config.embedding_model, dim=config.embedding_dim)
        return CachedEmbedder(inner, INTERIM_ROOT / "emb_cache.jsonl")
    raise ValueError(f"unsupported embedder: {kind}")


def load_search_documents(pack: Path) -> tuple[list[SearchDoc], dict[str, dict[str, Any]]]:
    """검색용 발화·교안 조각과 어려운 오답 출력에 필요한 원 필드를 읽는다."""
    docs: list[SearchDoc] = []
    details: dict[str, dict[str, Any]] = {}

    transcript_dir = pack / "index" / "transcripts"
    for path in sorted(transcript_dir.glob("*.jsonl")):
        for row in read_jsonl(path):
            doc_id = row["evidence_id"]
            if doc_id in details:
                raise ValueError(f"duplicate evidence id: {doc_id}")
            docs.append(
                SearchDoc(
                    doc_id=doc_id,
                    text=row["evidence_text_ko"],
                    lecture_id=row["lecture_id"],
                    evidence_type="TRANSCRIPT",
                )
            )
            details[doc_id] = row

    slides_dir = pack / "index" / "slides-v4"
    for path in sorted(slides_dir.glob("*.jsonl")):
        if path.name.startswith("6.172"):
            continue
        for row in read_jsonl(path):
            doc_id = row["source_key"]
            if doc_id in details:
                raise ValueError(f"duplicate evidence id: {doc_id}")
            docs.append(
                SearchDoc(
                    doc_id=doc_id,
                    text=row["text"],
                    lecture_id=row["lecture_id"],
                    evidence_type="DOCUMENT",
                )
            )
            details[doc_id] = row

    return docs, details


def build_searcher(
    pack: Path,
    embedder_kind: str,
    config: RetrievalConfig = DEFAULT_CONFIG,
) -> tuple[HybridSearcher, dict[str, dict[str, Any]], Embedder]:
    docs, details = load_search_documents(pack)
    embedder = make_embedder(embedder_kind, config)
    return HybridSearcher(docs, embedder, config), details, embedder


def count_distribution(values: Iterable[int]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for value in values:
        key = str(value)
        distribution[key] = distribution.get(key, 0) + 1
    return dict(sorted(distribution.items(), key=lambda item: int(item[0])))


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
