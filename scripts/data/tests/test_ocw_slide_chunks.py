import io
import zipfile

import pytest
from ocw_slide_chunks import (
    chunk_document,
    chunk_page,
    find_docs,
    is_garbled,
    is_low_content,
    page_paragraphs,
    read_pptx_pages,
)


def count(text: str) -> int:
    return len(text.split())


def split_tokens(text: str, n: int) -> list[str]:
    w = text.split()
    return [" ".join(w[i : i + n]) for i in range(0, len(w), n)]


def tail(text: str, n: int) -> str:
    return " ".join(text.split()[-n:])


def words(text: str) -> int:
    """가짜 내용어 수: 두 글자 이상인 단어."""
    return sum(len(w) > 1 for w in text.split())


def test_short_page_is_one_chunk():
    assert chunk_page(["a b c", "d e"], count, split_tokens, 10) == ["a b c\nd e"]


def test_long_page_splits_by_paragraph_then_sentence_then_token():
    paras = ["p1 " * 6, "p2 " * 6]
    assert chunk_page([p.strip() for p in paras], count, split_tokens, 8) == ["p1 " * 5 + "p1", "p2 " * 5 + "p2"]
    para = "One two three four. Five six seven eight. Nine ten."
    assert chunk_page([para], count, split_tokens, 5) == ["One two three four.", "Five six seven eight.", "Nine ten."]
    assert chunk_page(["x " * 12], count, split_tokens, 5) == ["x x x x x", "x x x x x", "x x"]


def test_no_overlap_option_and_no_page_crossing():
    pages = [["alpha " * 9], ["beta " * 3]]
    rows, st = chunk_document(pages, "C_L01", "D", count, split_tokens, max_tokens=5, content_words=words, min_chars=1)
    assert [r["source_key"] for r in rows] == ["C_L01_D1_1", "C_L01_D1_2", "C_L01_D2_1"]
    assert [r["page_no"] for r in rows] == [1, 1, 2]
    assert [r["chunk_index"] for r in rows] == [1, 2, 3]
    assert " ".join(r["text"] for r in rows if r["page_no"] == 1).split() == ["alpha"] * 9
    assert st["split_pages"] == 1


def test_overlap_within_page_only():
    page1 = " ".join(f"w{i}" for i in range(30))
    pages = [[page1], [" ".join(f"v{i}" for i in range(6))]]
    rows, st = chunk_document(pages, "C_L01", "D", count, split_tokens, 12, 3, tail, words, min_chars=1)
    p1 = [r["text"].split() for r in rows if r["page_no"] == 1]
    assert len(p1) > 1 and all(len(p) <= 12 for p in p1)
    for prev, cur in zip(p1, p1[1:], strict=False):
        assert cur[:3] == prev[-3:]  # 이웃 조각이 3토큰 겹침
    assert sorted({w for p in p1 for w in p}) == sorted(page1.split())  # 빠진 단어 없음
    # 쪽 사이 겹침 없음
    assert [r["text"].split() for r in rows if r["page_no"] == 2] == [[f"v{i}" for i in range(6)]]
    assert st["max_chunk_tokens"] <= 12 and st["split_pages"] == 1


def test_overlap_sentence_split_stays_under_max():
    para = " ".join(f"s{i} a b c." for i in range(10))  # 문장 10개, 각 4토큰
    pieces = chunk_page([para], count, split_tokens, 10, 2, tail)
    assert len(pieces) > 1 and all(count(p) <= 10 for p in pieces)
    assert all(p.split()[:2] == q.split()[-2:] for q, p in zip(pieces, pieces[1:], strict=False))


def test_overlap_needs_tail_and_sane_size():
    with pytest.raises(ValueError):
        chunk_page(["x " * 20], count, split_tokens, 10, 2, None)
    with pytest.raises(ValueError):
        chunk_page(["x " * 20], count, split_tokens, 10, 5, tail)


def test_low_content_rule():
    assert is_low_content("short", words)  # 20자 미만
    assert is_low_content("a b c d e f g h i j k l m n o p q r", words)  # 20자 이상이지만 내용어 0
    assert is_low_content("Lecture  12   and  x  y  z  w", words, min_content_words=4)
    assert not is_low_content("Dynamic programming uses memoization", words)


def test_low_content_pages_excluded_and_counted():
    pages = [["12"], ["x = 1 + 2 + 3 + 4 + 5 + 6"], ["Binary search halves the interval"], ["tiny"]]
    rows, st = chunk_document(pages, "C_L01", "D", count, split_tokens, 50, content_words=words)
    assert [r["source_key"] for r in rows] == ["C_L01_D3_1"]  # 다음 쪽에 붙이지 않음
    assert st["page_count"] == 4 and st["chunk_count"] == 1 and st["excluded_low_content"] == 3


def test_kiwi_content_words_if_installed():
    pytest.importorskip("kiwipiepy")
    from ocw_slide_chunks import content_word_count

    assert content_word_count("동적 계획법은 부분 문제의 답을 저장한다") >= 3
    assert content_word_count("x = y + z") == 0
    assert content_word_count("Big-O notation 표기법") >= 3


def test_third_party_and_boilerplate_removed():
    kept, removed, _ = page_paragraphs(
        [
            "Real content here",
            "© Someone. All rights reserved. This content is excluded from our Creative Commons license.",
            "12",
            "MIT OpenCourseWare\nhttps://ocw.mit.edu",
        ]
    )
    assert kept == ["Real content here"]
    assert removed == 1


def test_copyright_line_removed_inside_block():
    blocks = ["WHY PERFORMANCE\nENGINEERING?\n© 2008–2018 by the MIT 6.172 Lecturers",
              "Intro\n(c) 2012-2018 by the Lecturers of MIT 6.172",
              "Stack memory. 2008-2018 by the © 2008 MIT 6.172 Lecturers 2018"]
    kept, _, garbled = page_paragraphs(blocks)
    assert kept == ["WHY PERFORMANCE ENGINEERING?", "Intro", "Stack memory."] and garbled == 0


def test_garbled_lines_dropped_and_counted():
    block = "!\"##$*\n%&'&(! \"#)*+)$#)*+,*-./01*\nCache Coherence\n! ! ! # $ $"
    kept, _, garbled = page_paragraphs([block])
    assert kept == ["Cache Coherence"] and garbled == 3
    rows, st = chunk_document([[block], ["!\"##$* %&'&("]], "C_L01", "D", count, split_tokens, 50,
                              content_words=words, min_chars=1, min_content_words=1)
    assert [r["page_no"] for r in rows] == [1]
    assert st["garbled_blocks"] == 4 and st["excluded_low_content"] == 1


def test_normal_text_and_code_kept():
    for line in [
        "Dynamic programming stores answers to subproblems.",
        "동적 계획법은 부분 문제의 답을 저장한다.",
        "x = a[i]",
        "L[i] = L[i] + 1",
        "def sqrt(x, eps):",
        "O(n log n) vs Θ(n²)",
        "for i in range(n):",
        "for (int i = 0; i < n; ++i) {",
        "Example: !\"#$%",
        "P P P",
    ]:
        assert not is_garbled(line), line
    assert is_garbled("!\"##$* %&'&(")
    assert is_garbled("'(%!74 :;%0.4:;+04 B<)4")


def test_find_docs_maps_lectures_and_dedupes():
    names = [
        "static_resources/a2c80596cf4a2b5fbc854afdd2f23dcb_MIT6_006S20_lec7.pdf",
        "static_resources/mit6_006s20_lec18.pdf",
        "static_resources/0123456789abcdef0123456789abcdef_MIT6_006S20_lec18.pdf",
        "static_resources/c6d8f06c6f11e3342633dec85498f551_MIT6_006S20_r01.pdf",
    ]
    assert [(d[1], d[2]) for d in find_docs("6.006_S20", names)] == [("6.006_S20_L07", "D"), ("6.006_S20_L18", "D")]
    fixed = ["static_resources/fcd808125be09dd585ec3ec01c46726d_MIT6_034F10_netmath.pdf"]
    assert find_docs("6.034_F10", fixed)[0][1] == "6.034_F10_L12A"


def test_pptx_reads_slides_not_notes():
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'

    def slide(*paras):
        body = "".join(f"<a:p><a:r><a:t>{p}</a:t></a:r></a:p>" for p in paras)
        return f"<root {ns}>{body}</root>"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/slides/slide2.xml", slide("second"))
        z.writestr("ppt/slides/slide1.xml", slide("Title", "bullet"))
        z.writestr("ppt/notesSlides/notesSlide1.xml", slide("speaker note"))
    assert read_pptx_pages(buf.getvalue()) == [["Title", "bullet"], ["second"]]
