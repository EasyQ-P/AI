"""평가모듈 (L2) — T-09, T-10. 담당: 최의찬, 엄윤종."""


def select_threshold(scores: list[float], labels: list[int], max_fpr: float = 0.04) -> float:
    """질문별 최고 점수 · 라벨로 검증셋 FPR ≤ max_fpr를 만족하는 가장 낮은 τ를 고른다."""
    pairs = sorted(zip(scores, labels, strict=True), reverse=True)
    negatives = sum(1 for _, y in pairs if y == 0)
    if negatives == 0:
        return min(scores)
    best = float("inf")
    fp = 0
    for i, (s, y) in enumerate(pairs):
        if y == 0:
            fp += 1
        if fp / negatives > max_fpr:
            break
        if i + 1 == len(pairs) or pairs[i + 1][0] < s:
            best = s
    return best


def evaluate(model, dataset_version: str, max_fpr: float = 0.04):
    """EvalReport(τ · roc_auc · false_answer_rate · tpr · roc_points · service_metrics)."""
    raise NotImplementedError


def run_baselines(dataset_version: str, llm_model_id: str, prompt_version: str):
    """베이스라인 3종 결과와 τ_LLM."""
    raise NotImplementedError
