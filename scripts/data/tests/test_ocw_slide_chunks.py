import io
import zipfile

from ocw_slide_chunks import chunk_document, chunk_page, find_docs, page_paragraphs, read_pptx_pages


def count(text: str) -> int:
    return len(text.split())


def split_tokens(text: str, n: int) -> list[str]:
    w = text.split()
    return [" ".join(w[i : i + n]) for i in range(0, len(w), n)]


def test_short_page_is_one_chunk():
    assert chunk_page(["a b c", "d e"], count, split_tokens, 10) == ["a b c\nd e"]


def test_long_page_splits_by_paragraph_then_sentence_then_token():
    paras = ["p1 " * 6, "p2 " * 6]
    assert chunk_page([p.strip() for p in paras], count, split_tokens, 8) == ["p1 " * 5 + "p1", "p2 " * 5 + "p2"]
    para = "One two three four. Five six seven eight. Nine ten."
    assert chunk_page([para], count, split_tokens, 5) == ["One two three four.", "Five six seven eight.", "Nine ten."]
    assert chunk_page(["x " * 12], count, split_tokens, 5) == ["x x x x x", "x x x x x", "x x"]


def test_no_overlap_and_no_page_crossing():
    pages = [["alpha " * 9], ["beta " * 3]]
    rows, st = chunk_document(pages, "C_L01", "D", count, split_tokens, max_tokens=5, min_page_tokens=2)
    assert [r["source_key"] for r in rows] == ["C_L01_D1_1", "C_L01_D1_2", "C_L01_D2_1"]
    assert [r["page_no"] for r in rows] == [1, 1, 2]
    assert [r["chunk_index"] for r in rows] == [1, 2, 3]
    assert " ".join(r["text"] for r in rows if r["page_no"] == 1).split() == ["alpha"] * 9
    assert st["split_pages"] == 1


def test_short_pages_skipped_and_counted():
    rows, st = chunk_document([["tiny"], ["enough words here ok"]], "C_L01", "D", count, split_tokens, 50, 3)
    assert [r["page_no"] for r in rows] == [2]
    assert st["short_pages"] == 1


def test_third_party_and_boilerplate_removed():
    kept, removed = page_paragraphs(
        [
            "Real content here",
            "© Someone. All rights reserved. This content is excluded from our Creative Commons license.",
            "12",
            "MIT OpenCourseWare\nhttps://ocw.mit.edu",
        ]
    )
    assert kept == ["Real content here"]
    assert removed == 1


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
