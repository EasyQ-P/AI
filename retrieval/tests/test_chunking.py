import re

import pytest

from retrieval.chunking import (
    OCW_DROP_PATTERNS,
    OCW_STRIP_PATTERNS,
    chunk_page,
    chunk_slides,
    chunk_slides_with_stats,
    chunk_utterances,
    count_content_words,
    is_garbled,
    is_low_content,
    page_paragraphs,
)
from retrieval.config import RetrievalConfig


def ws_spans(text: str) -> list[tuple[int, int]]:
    """시험용 토크나이저: 공백으로 나눈 낱말 하나 = 토큰 하나."""
    return [m.span() for m in re.finditer(r"\S+", text)]


SMALL = RetrievalConfig(slide_max_tokens=10, slide_overlap_tokens=3)


def test_one_page_one_chunk_and_page_numbers_kept():
    pages = [["Binary search trees", "store keys in order"], [], ["Hash tables use hashing for lookup"]]
    chunks = chunk_slides(pages, ws_spans)
    assert [(c.page_no, c.part) for c in chunks] == [(1, 1), (3, 1)]
    assert chunks[0].text == "Binary search trees\nstore keys in order"
    assert chunks[0].token_count == 7


def test_string_page_is_split_into_blocks_on_blank_lines():
    chunks = chunk_slides(["Binary search\ntrees\n\nstore keys in order"], ws_spans)
    assert chunks[0].text == "Binary search trees\nstore keys in order"


def test_block_lines_and_hyphens_are_joined():
    paras, _, _ = page_paragraphs(["Divide and con-\nquer splits   the\nproblem", "12"])
    assert paras == ["Divide and conquer splits the problem"]  # 쪽 번호만 있는 문단은 버린다


def test_long_page_splits_by_paragraph_then_overlaps_on_word_boundary():
    paras = [" ".join(f"a{i}" for i in range(6)), " ".join(f"b{i}" for i in range(6)), "c0 c1 c2"]
    pieces = chunk_page(paras, ws_spans, SMALL)
    # 예산 = 10 - 3 = 7토큰 안으로 문단을 묶고, 둘째 조각부터 앞 조각 끝 3토큰을 붙인다
    assert pieces == ["a0 a1 a2 a3 a4 a5", "a3 a4 a5 b0 b1 b2 b3 b4 b5", "b3 b4 b5 c0 c1 c2"]
    assert all(len(p.split()) <= 10 for p in pieces)


def test_long_sentence_falls_back_to_token_split():
    words = [f"w{i}" for i in range(20)]
    chunks = chunk_slides([[" ".join(words)], ["Another short page with enough words"]], ws_spans, SMALL)
    first = [c for c in chunks if c.page_no == 1]
    assert [c.part for c in first] == [1, 2, 3]
    assert [c.token_count for c in first] == [7, 10, 9]
    assert first[0].text.split()[-3:] == first[1].text.split()[:3]
    assert first[-1].text.split()[-1] == "w19"
    assert chunks[-1].page_no == 2  # 쪽을 넘겨 붙이지 않는다


def test_short_or_contentless_pages_are_skipped():
    assert chunk_slides([["Lecture 1"]], ws_spans) == []                       # 20자 미만
    assert chunk_slides([["1 2 3 4 5 6 7 8 9 10 11 12"]], ws_spans) == []    # 내용어 없음
    assert is_low_content("Lecture  \n\n  1 x") is True                       # 공백 정리 뒤에 센다


def test_garbled_lines_removed_but_code_lines_kept():
    assert is_garbled("#$%^&*@!~ ¤¤¤")
    assert not is_garbled("L[i] = L[i] + 1")
    assert not is_garbled("x = a [ i ] + b")  # 2글자 이하 기호 토큰은 세지 않는다
    paras, _, garbled = page_paragraphs(["Real sentence here\n#$%^&*@!~ ¤¤¤\nNext line"])
    assert paras == ["Real sentence here Next line"]
    assert garbled == 1


def test_ocw_patterns_strip_copyright_and_drop_third_party():
    blocks = [
        "Cache misses matter © 2008–2018 by the MIT 6.172 Lecturers",
        "Image courtesy of someone. All rights reserved.",
        "Work and span analysis",
    ]
    chunks, stats = chunk_slides_with_stats(
        [blocks], ws_spans, strip_patterns=OCW_STRIP_PATTERNS, drop_patterns=OCW_DROP_PATTERNS)
    assert chunks[0].text == "Cache misses matter\nWork and span analysis"
    assert stats.third_party_blocks == 1
    # 서비스(패턴 없음)는 지우지 않는다
    assert "All rights reserved" in chunk_slides([blocks], ws_spans)[0].text


def test_stats_count_pages():
    _, stats = chunk_slides_with_stats([["Lecture 1"], ["Binary search trees store keys in order"]], ws_spans)
    assert (stats.page_count, stats.chunk_count, stats.excluded_low_content) == (2, 1, 1)


def test_content_words_korean_needs_kiwi():
    pytest.importorskip("kiwipiepy")
    assert count_content_words("이진 탐색 트리는 키를 정렬된 순서로 저장한다") >= 3


def test_overlap_must_be_smaller_than_half_of_max():
    with pytest.raises(ValueError):
        chunk_slides([["x"]], ws_spans, RetrievalConfig(slide_max_tokens=10, slide_overlap_tokens=5))


def test_utterances_group_by_30_seconds():
    segs = [(31_000, 33_000, "셋"), (0, 4_000, " 하나 "), (10_000, 29_000, "둘"), (45_000, 50_000, ""),
            (61_000, 62_000, "넷")]
    chunks = chunk_utterances(segs)
    assert [(c.text, c.start_ms, c.end_ms) for c in chunks] == [
        ("하나 둘", 0, 29_000), ("셋", 31_000, 33_000), ("넷", 61_000, 62_000)]
