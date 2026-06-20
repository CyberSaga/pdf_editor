from scripts.fusion_eval import EvalCase, score_answer


def test_eval_rewards_required_coverage_and_valid_links():
    case = EvalCase(
        required_terms=("rollback", "timeout"),
        forbidden_terms=("guaranteed safe",),
        require_links=True,
    )

    score = score_answer(
        case,
        "Use a rollback and timeout. Source: https://example.com/guidance",
    )

    assert score.required_coverage == 1.0
    assert score.forbidden_hits == ()
    assert score.valid_links == ("https://example.com/guidance",)
    assert score.total == 1.0


def test_eval_penalizes_unsafe_claims_and_missing_coverage():
    case = EvalCase(
        required_terms=("rollback", "timeout"),
        forbidden_terms=("guaranteed safe",),
        require_links=False,
    )

    score = score_answer(case, "This is guaranteed safe with a timeout.")

    assert score.required_coverage == 0.5
    assert score.forbidden_hits == ("guaranteed safe",)
    assert score.total < 0.5


def test_eval_can_compare_stored_direct_and_fused_answers():
    case = EvalCase(
        required_terms=("consensus", "contradiction", "uncertainty"),
        forbidden_terms=(),
        require_links=False,
    )

    direct = score_answer(case, "There is consensus.")
    fused = score_answer(case, "Consensus exists, but preserve contradiction and uncertainty.")

    assert fused.total > direct.total
