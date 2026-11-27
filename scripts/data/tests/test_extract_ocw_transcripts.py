from extract_ocw_transcripts import code_for, slug


def test_code_for():
    assert code_for("Lecture 3: Sets and Sorting") == "L03"
    assert code_for("Lecture 12A: Neural Nets") == "L12A"
    assert code_for("Quiz 2 Review") == "QR2"
    assert code_for("Problem Session 7") == "PS7"
    assert code_for("Recitation 5: Dynamic Programming") == "R05"
    assert code_for("Mega-Recitation 3: Games") == "MR3"
    assert code_for("Meet the Educator") is None


def test_slug():
    assert slug("Lecture 21: Algorithms—Next Steps") == "Algorithms_Next_Steps"
    assert slug("Quiz 1 Review") == "Quiz_1_Review"
    assert slug("Problem Session 3") == "Problem_Session_3"
