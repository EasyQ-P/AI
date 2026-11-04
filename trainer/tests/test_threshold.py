import math

from modules.evaluate import select_threshold


def test_threshold_keeps_fpr_under_limit():
    # 음성 10개 중 최고점 1개만 τ 위로 올라가면 FPR 10% → 4% 기준에서는 그 위로 τ를 잡아야 한다
    scores = [0.95, 0.9, 0.8, 0.7] + [0.85] + [0.1] * 9
    labels = [1, 1, 1, 1] + [0] + [0] * 9
    tau = select_threshold(scores, labels, max_fpr=0.04)
    assert tau == 0.9
    assert select_threshold(scores, labels, max_fpr=0.1) == 0.7


def test_threshold_above_max_when_nothing_qualifies():
    # 최고점이 음성이면 어떤 τ도 FPR 0%를 못 맞춘다 → 최고점 바로 위(유한한 값)로 모두 이관
    scores = [0.99, 0.5, 0.2]
    labels = [0, 1, 0]
    tau = select_threshold(scores, labels, max_fpr=0.0)
    assert math.isfinite(tau)
    assert tau > max(scores)
    assert all(s < tau for s in scores)
