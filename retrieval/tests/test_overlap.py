from retrieval.overlap import check_overlap, is_eval_lecture, normalize, overlap_ratio
from retrieval.search import rrf_merge

EVAL = ["Backpropagation computes the gradient of the loss with respect to each weight by the chain rule."]


def test_normalize():
    assert normalize("  Ｂackprop,  역전파는!! ") == "backprop 역전파는"


def test_same_chunk_overlaps_fully():
    assert overlap_ratio(EVAL[0], EVAL) == 1.0


def test_unrelated_chunk_does_not_overlap():
    assert overlap_ratio("오늘은 운영체제의 스케줄링 알고리즘을 배워 봅시다 그리고 예제를 풉니다", EVAL) == 0.0


def test_short_chunk_uses_exact_match():
    assert overlap_ratio("Chain rule!", ["chain rule"]) == 1.0
    assert overlap_ratio("chain rule", ["chain rules"]) == 0.0


def test_eval_lecture_needs_30_percent():
    lecture = [EVAL[0], "다른 내용 하나 둘 셋 넷 다섯 여섯", "또 다른 내용 하나 둘 셋 넷 다섯"]
    assert is_eval_lecture(lecture, EVAL)          # 1/3 ≥ 0.3
    assert not is_eval_lecture(lecture + lecture[1:] * 2, EVAL)  # 1/7 < 0.3


def test_check_overlap_splits_items():
    passed, excluded = check_overlap([EVAL[0], "전혀 관계없는 질문 내용 입니다 정말로"], EVAL)
    assert passed == [1] and excluded == [0]


def test_rrf_merge_prefers_items_in_both_lists():
    assert rrf_merge(["a", "b", "c"], ["c", "d"], top_n=2) == ["c", "a"]
