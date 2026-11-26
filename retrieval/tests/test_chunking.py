import re

import pytest

from retrieval.chunking import chunk_slides, chunk_utterances, clean_page, count_content_words
from retrieval.config import RetrievalConfig


def ws_spans(text: str) -> list[tuple[int, int]]:
    """시험용 토크나이저: 공백으로 나눈 낱말 하나 = 토큰 하나."""
    return [m.span() for m in re.finditer(r"\S+", text)]


SMALL = RetrievalConfig(slide_max_tokens=10, slide_overlap_tokens=3)


def test_one_page_one_chunk_and_page_numbers_kept():
    pages = ["Binary search trees store keys in order", "", "Hash tables use hashing for lookup"]
    chunks = chunk_slides(pages, ws_spans)
    assert [(c.page_no, c.part) for c in chunks] == [(1, 1), (3, 1)]
    assert chunks[0].token_count == 7


def test_long_page_splits_with_overlap_and_never_crosses_pages():
    words = [f"word{i}" for i in range(25)]
    chunks = chunk_slides([" ".join(words), "Another short page with enough words"], ws_spans, SMALL)
    first_page = [c for c in chunks if c.page_no == 1]
    assert [c.part for c in first_page] == [1, 2, 3, 4]
    assert [c.token_count for c in first_page] == [10, 10, 10, 4]
    # 앞 조각의 마지막 3토큰 = 다음 조각의 처음 3토큰
    assert first_page[0].text.split()[-3:] == first_page[1].text.split()[:3]
    assert first_page[-1].text.split()[-1] == "word24"
    assert chunks[-1].page_no == 2


def test_short_or_contentless_pages_are_skipped():
    assert chunk_slides(["Lecture 1"], ws_spans) == []          # 20자 미만
    assert chunk_slides(["1 2 3 4 5 6 7 8 9 10 11 12"], ws_spans) == []  # 내용어 없음


def test_garbled_lines_are_removed():
    assert clean_page("Real sentence here\n#$%^&*@!~ ¤¤¤\n  \nNext line") == "Real sentence here\nNext line"


def test_content_words_korean_needs_kiwi():
    pytest.importorskip("kiwipiepy")
    assert count_content_words("이진 탐색 트리는 키를 정렬된 순서로 저장한다") >= 3


def test_overlap_must_be_smaller_than_max():
    with pytest.raises(ValueError):
        chunk_slides(["x"], ws_spans, RetrievalConfig(slide_max_tokens=5, slide_overlap_tokens=5))


def test_utterances_group_by_30_seconds():
    segs = [(31_000, 33_000, "셋"), (0, 4_000, " 하나 "), (10_000, 29_000, "둘"), (45_000, 50_000, ""),
            (61_000, 62_000, "넷")]
    chunks = chunk_utterances(segs)
    assert [(c.text, c.start_ms, c.end_ms) for c in chunks] == [
        ("하나 둘", 0, 29_000), ("셋", 31_000, 33_000), ("넷", 61_000, 62_000)]


def test_utterances_empty():
    assert chunk_utterances([]) == []
