from ocw_transcript_text import (
    INSTRUCTOR,
    OTHER,
    STUDENT,
    UNLABELED,
    Turn,
    assign_roles,
    clean_page_lines,
    clean_text,
    drop_cc_notice,
    lecture_code,
    process_pages,
    split_turns,
    video_kind,
)

CC = (
    "The following content is provided under a Creative Commons license. Your support will help\n"
    "MIT OpenCourseWare continue to offer high-quality, educational resources for free. To make\n"
    "a donation, or view additional materials from hundreds of MIT courses, visit MIT\n"
    "OpenCourseWare at ocw.mit.edu.\n"
)


def test_clean_page_lines_drops_header_and_leading_junk():
    lines = ["MITOCW | 1. Algorithms", "g", "y", ", p", "Real text here.", "ok"]
    assert clean_page_lines(lines) == ["Real text here.", "ok"]


def test_drop_cc_notice_variants():
    assert drop_cc_notice(CC + "Hello.").strip() == "Hello."
    odd = CC.replace("ocw.mit.edu.", "fsae@mit.edu.") + "It was in 2010."
    assert drop_cc_notice(odd).strip() == "It was in 2010."
    no_period = CC.replace("ocw.mit.edu.", "ocw.mit.edu") + "All right."
    assert drop_cc_notice(no_period).strip() == "All right."


def test_clean_text_removes_sound_tags_keeps_unsure_words_and_code():
    text = "[SQUEAKING] So [LAUGHTER] the [? UROP ?] student wrote A[i] [INAUDIBLE] here ."
    assert clean_text(text) == "So the UROP student wrote A[i] here."


def test_split_turns_label_forms():
    lines = [
        "Intro before any label.",
        "JASON KU:",
        "Good morning.",
        "AUDIENCE: Morning.",
        "TAO B. SCHARDL:You can avoid that.",
        "CHARLES E.",
        "LEISERSON:",
        "Welcome back.",
        "AUDIENCE: [INAUDIBLE] SPEAKER 1: Take the constants out.",
        "SPEAKER 1: Next one.",
    ]
    turns = split_turns(lines)
    assert [(t.speaker, t.text) for t in turns] == [
        (UNLABELED, "Intro before any label."),
        ("JASON KU", "Good morning."),
        ("AUDIENCE", "Morning."),
        ("TAO B. SCHARDL", "You can avoid that."),
        ("CHARLES E. LEISERSON", "Welcome back."),
        ("AUDIENCE", "[INAUDIBLE]"),
        ("SPEAKER 1", "Take the constants out."),
        ("SPEAKER 1", "Next one."),
    ]


def test_split_turns_does_not_take_sentence_end_as_name():
    turns = split_turns(["JASON KU:", "That is a DAG.", "OK.", "More text."])
    assert len(turns) == 1 and turns[0].speaker == "JASON KU"


def test_assign_roles():
    turns = [
        Turn("PATRICK WINSTON", "word " * 900),
        Turn("AUDIENCE", "question?"),
        Turn("STUDENT", "another question?"),
        Turn("LISA", "short answer"),
        Turn("SYSTEM", "beep"),
        Turn("LEISERSON", "brief remark"),
        Turn(UNLABELED, "opening words"),
    ]
    roles = assign_roles(turns, known_instructors={"LEISERSON"})
    assert roles == {
        "PATRICK WINSTON": INSTRUCTOR,
        "AUDIENCE": STUDENT,
        "STUDENT": STUDENT,
        "LISA": STUDENT,
        "SYSTEM": OTHER,
        "LEISERSON": INSTRUCTOR,
        UNLABELED: INSTRUCTOR,
    }


def test_process_pages_repairs_missing_instructor_label():
    long_tail = "\n".join(["Merge the two nodes into one. Yes. This is what we call contracting."] * 8)
    page = "ERIK DEMAINE:\nSo what can we do? Yeah?\nAUDIENCE:\nCan you merge the two nodes into one?\n" + long_tail
    turns = process_pages([page])
    assert [(t.speaker, t.role) for t in turns] == [
        ("ERIK DEMAINE", INSTRUCTOR),
        ("AUDIENCE", STUDENT),
        ("ERIK DEMAINE", INSTRUCTOR),
    ]
    assert turns[1].text == "Can you merge the two nodes into one?"
    assert turns[2].repaired


def test_process_pages_end_to_end():
    pages = [
        "MITOCW | 1. Algorithms and Computation\n" + CC + "[SQUEAKING]\nJASON KU:\nGood morning, everybody.\n"
        "STUDENT:\nMorning--\nJASON KU:\nMy name's Jason Ku.",
        "g\ny\nThis is Intro to Algorithms.",
    ]
    turns = process_pages(pages)
    instructor = " ".join(t.text for t in turns if t.role == INSTRUCTOR)
    assert instructor == "Good morning, everybody. My name's Jason Ku. This is Intro to Algorithms."


def test_lecture_code_and_kind():
    assert lecture_code("L12A_Neural_Nets.pdf") == "L12A"
    assert lecture_code("extras/X03_Branching.pdf") == "X03"
    assert [video_kind(c) for c in ("L01", "PS3", "QR1", "R05", "MR2", "T01", "X03")] == [
        "LECTURE",
        "PROBLEM_SESSION",
        "QUIZ_REVIEW",
        "RECITATION",
        "MEGA_RECITATION",
        "TUTORIAL",
        "EXTRA",
    ]
