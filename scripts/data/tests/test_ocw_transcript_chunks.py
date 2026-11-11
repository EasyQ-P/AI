from ocw_transcript_chunks import DEFAULT_WPM, chunk_lecture, chunk_words, split_sentences, target_words


def test_target_words_matches_design_example():
    # 설계서 3.1.2 예시: 약 5,700단어, 45분 31초 → 분당 약 125단어 → 30초에 약 60단어
    assert target_words(5700, 45 * 60 + 31) == 63
    assert target_words(1000, None) == round(DEFAULT_WPM / 2)


def test_split_sentences():
    assert split_sentences("One. Two? Three! four") == ["One.", "Two?", "Three!", "four"]


def sentence(n: int) -> str:
    return " ".join(["w"] * (n - 1)) + " end."


def test_chunk_words_respects_sentences_and_target():
    text = " ".join(sentence(20) for _ in range(9))  # 180단어
    chunks = chunk_words(text, 60)
    assert [len(c.split()) for c in chunks] == [60, 60, 60]
    assert all(c.endswith("end.") for c in chunks)


def test_chunk_words_splits_long_sentence_and_merges_short_tail():
    long_sentence = " ".join(["x"] * 200) + "."
    chunks = chunk_words(long_sentence + " " + sentence(10), 60)
    sizes = [len(c.split()) for c in chunks]
    assert sum(sizes) == 210
    assert sizes[-1] >= 30  # 짧은 꼬리(10단어)는 앞 청크에 붙는다


def test_chunk_lecture_fields():
    row = {"lecture_id": "6.006_S20_L01", "course_id": "6.006_S20", "text": " ".join(sentence(20) for _ in range(6))}
    meta = {"split": "TRAIN", "words_by_role": {"INSTRUCTOR": 1200, "STUDENT": 50}, "duration_sec": 600}
    chunks = chunk_lecture(row, meta)
    assert chunks[0]["evidence_id"] == "6.006_S20_L01_T0001"
    assert chunks[0]["target_words"] == 62  # 1,250단어 / 10분 = 분당 125단어
    assert {c["evidence_type"] for c in chunks} == {"TRANSCRIPT"}
    assert all(c["start_ms"] is None and c["end_ms"] is None for c in chunks)
    assert sum(c["word_count"] for c in chunks) == 120
