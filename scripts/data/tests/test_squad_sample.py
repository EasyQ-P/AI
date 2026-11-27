from squad_sample import build, cut_around, sentence_spans


def count(text: str) -> int:
    return len(text.split())


CTX = "S one is here. S two is here. S three has ANSWER inside. S four is here. S five is here."


def test_sentence_spans():
    assert [CTX[s:e] for s, e in sentence_spans(CTX)][:2] == ["S one is here.", "S two is here."]


def test_cut_centers_anchor_and_respects_limits():
    pos = CTX.index("ANSWER")
    text, start = cut_around(CTX, pos, count, target_words=12, max_tokens=100)
    assert text == "S two is here. S three has ANSWER inside. S four is here."
    assert CTX[start:].startswith(text)
    text, _ = cut_around(CTX, pos, count, target_words=100, max_tokens=13)
    assert "ANSWER" in text and count(text) <= 13


def make_data():
    data = []
    for t in range(6):
        paras = []
        for p in range(3):
            ctx = f"Intro {t}{p} sentence. The key fact {t}{p} is here. Outro sentence."
            pos = ctx.index("key")
            paras.append(
                {
                    "context": ctx,
                    "qas": [
                        {"id": f"a{t}{p}", "question": "q?", "is_impossible": False,
                         "answers": [{"text": "key", "answer_start": pos}]},
                        {"id": f"i{t}{p}", "question": "q?", "is_impossible": True, "answers": [],
                         "plausible_answers": [{"text": "key", "answer_start": pos}]},
                    ],
                }
            )
        data.append({"title": f"T{t}", "paragraphs": paras})
    return data


def test_build_balanced_one_question_per_paragraph():
    pairs, report = build(make_data(), count, n_per_label=4, seed=1, per_title=1, target_words=50, max_tokens=350)
    labels = [p["label"] for p in pairs]
    assert labels.count("ANSWERABLE") == 4 and labels.count("INSUFFICIENT_EVIDENCE") == 4
    paras = [p["evidence_text"] for p in pairs]
    assert len(set(paras)) == len(paras)  # 한 지문에서 질문 하나
    assert all(p["split"] == "TRAIN" and p["label_source"] == "PUBLIC" for p in pairs)
    assert all(p["target"] == (p["label"] == "ANSWERABLE") for p in pairs)
    for lab in ("ANSWERABLE", "INSUFFICIENT_EVIDENCE"):
        titles = [p["squad_title"] for p in pairs if p["label"] == lab]
        assert len(set(titles)) == len(titles)  # 문서당 라벨별 1개
