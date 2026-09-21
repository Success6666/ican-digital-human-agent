"""Tests for the offline retrieval metrics and paired comparison."""

from __future__ import annotations

import pytest

from app.rag.tuning import (
    RetrievalCase,
    average_precision,
    compare_configurations,
    evaluate_retrieval,
    hit_rate_at_k,
    ndcg_at_k,
    paired_bootstrap,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def _case(retrieved: list[str], relevant: set[str], query: str = "q") -> RetrievalCase:
    return RetrievalCase(query=query, relevant=frozenset(relevant), retrieved=tuple(retrieved))


def test_recall_counts_share_of_judged_relevant_passages() -> None:
    case = _case(["a", "b", "c"], {"b", "d"})
    assert recall_at_k(case, 2) == 0.5
    assert recall_at_k(case, 3) == 0.5
    assert recall_at_k(case, 1) == 0.0


def test_precision_uses_returned_length_so_short_lists_are_not_rewarded() -> None:
    # Only one passage returned and it is relevant: precision is 1.0, not 1/k.
    assert precision_at_k(_case(["a"], {"a"}), 5) == 1.0
    assert precision_at_k(_case(["x", "y"], {"a"}), 5) == 0.0
    assert precision_at_k(_case(["x", "a"], {"a"}), 5) == 0.5


def test_reciprocal_rank_uses_first_relevant_position() -> None:
    assert reciprocal_rank(_case(["x", "y", "a"], {"a"})) == pytest.approx(1 / 3)
    assert reciprocal_rank(_case(["a", "y"], {"a"})) == 1.0
    assert reciprocal_rank(_case(["x", "y"], {"a"})) == 0.0


def test_average_precision_averages_precision_at_each_relevant_hit() -> None:
    # Relevant at ranks 1 and 3: (1/1 + 2/3) / 2
    assert average_precision(_case(["a", "x", "b"], {"a", "b"})) == pytest.approx((1.0 + 2 / 3) / 2)


def test_ndcg_is_one_for_a_perfect_ranking_and_discounts_late_hits() -> None:
    perfect = _case(["a", "b"], {"a", "b"})
    assert ndcg_at_k(perfect, 2) == pytest.approx(1.0)
    late = _case(["x", "y", "a"], {"a"})
    assert 0.0 < ndcg_at_k(late, 3) < 1.0


def test_hit_rate_is_binary() -> None:
    assert hit_rate_at_k(_case(["x", "a"], {"a"}), 2) == 1.0
    assert hit_rate_at_k(_case(["x", "a"], {"a"}), 1) == 0.0


def test_degenerate_inputs_return_zero_rather_than_raising() -> None:
    empty = _case([], set())
    assert recall_at_k(empty, 5) == 0.0
    assert precision_at_k(empty, 5) == 0.0
    assert reciprocal_rank(empty) == 0.0
    assert ndcg_at_k(empty, 5) == 0.0
    assert average_precision(empty) == 0.0
    assert recall_at_k(_case(["a"], {"a"}), 0) == 0.0


def test_evaluate_retrieval_summarizes_all_families_of_metric() -> None:
    cases = [
        _case(["a", "x", "y"], {"a"}),
        _case(["x", "b", "y"], {"b"}),
        _case(["x", "y", "z"], {"c"}, query="missing"),
    ]
    report = evaluate_retrieval(cases, k_values=(1, 3))

    assert report.case_count == 3
    assert report.empty_result_cases == 0
    assert report.misses == ["missing"]
    assert report.metrics["mrr"].mean == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    assert report.metrics["recall@1"].mean == pytest.approx(1 / 3)
    assert report.metrics["recall@3"].mean == pytest.approx(2 / 3)
    assert report.metrics["ndcg@3"].sample_count == 3
    assert report.metrics["mrr"].lower is not None


def test_evaluate_retrieval_counts_empty_results() -> None:
    report = evaluate_retrieval([_case([], {"a"})])
    assert report.empty_result_cases == 1
    assert report.metrics["mrr"].mean == 0.0


def test_paired_bootstrap_detects_a_consistent_improvement() -> None:
    baseline = [0.0, 0.1, 0.2, 0.05, 0.0, 0.15, 0.2, 0.1]
    candidate = [0.3, 0.4, 0.5, 0.35, 0.3, 0.45, 0.5, 0.4]
    result = paired_bootstrap(baseline, candidate, samples=500)
    assert result["significant"] is True
    assert result["mean_delta"] > 0
    assert result["lower"] > 0
    assert result["wins"] == 8
    assert result["losses"] == 0


def test_paired_bootstrap_reports_a_regression_as_significant_too() -> None:
    baseline = [0.5, 0.6, 0.55, 0.7, 0.65]
    candidate = [0.1, 0.2, 0.15, 0.3, 0.25]
    result = paired_bootstrap(baseline, candidate, samples=500)
    assert result["significant"] is True
    assert result["upper"] < 0
    assert result["losses"] == 5


def test_paired_bootstrap_finds_no_effect_when_only_noise_differs() -> None:
    baseline = [0.1, 0.5, 0.3, 0.7, 0.2, 0.9, 0.4, 0.6]
    candidate = [0.6, 0.1, 0.8, 0.2, 0.7, 0.3, 0.9, 0.4]
    result = paired_bootstrap(baseline, candidate, samples=2000)
    assert result["lower"] <= 0.0 <= result["upper"]
    assert result["significant"] is False
    assert result["wins"] > 0 and result["losses"] > 0


def test_paired_bootstrap_is_deterministic_for_a_fixed_seed() -> None:
    baseline = [0.0, 0.1, 0.2]
    candidate = [0.2, 0.3, 0.4]
    first = paired_bootstrap(baseline, candidate, samples=300, seed=7)
    second = paired_bootstrap(baseline, candidate, samples=300, seed=7)
    assert first == second


def test_paired_bootstrap_rejects_misaligned_samples() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap([0.1], [0.2, 0.3])


def test_paired_bootstrap_handles_no_cases() -> None:
    result = paired_bootstrap([], [])
    assert result["samples"] == 0
    assert result["significant"] is False


def test_compare_configurations_reports_both_means_and_the_delta() -> None:
    baseline = [_case(["x", "a"], {"a"}), _case(["x", "y", "b"], {"b"})]
    candidate = [_case(["a", "x"], {"a"}), _case(["b", "y"], {"b"})]
    comparison = compare_configurations(baseline, candidate, metric="mrr", k_values=(1, 3))

    assert comparison["metric"] == "mrr"
    assert comparison["baseline_mean"] == pytest.approx((0.5 + 1 / 3) / 2)
    assert comparison["candidate_mean"] == pytest.approx(1.0)
    assert comparison["mean_delta"] > 0


def test_compare_configurations_supports_k_suffixed_metric_names() -> None:
    baseline = [_case(["x", "a"], {"a"})]
    candidate = [_case(["a", "x"], {"a"})]
    assert compare_configurations(baseline, candidate, metric="recall@2")["candidate_mean"] == 1.0
    assert compare_configurations(baseline, candidate, metric="precision@1")["candidate_mean"] == 1.0


def test_compare_configurations_rejects_an_unknown_metric() -> None:
    with pytest.raises(ValueError):
        compare_configurations([_case(["a"], {"a"})], [_case(["a"], {"a"})], metric="bogus")
