"""事实有据性指标。"""

from __future__ import annotations

from collections.abc import Iterable

from .models import EvaluationDimension, MetricScore


def grounding_score(output: str, evidence: Iterable[str], expected: Iterable[str]) -> MetricScore:
    expected_terms = [term.casefold() for term in expected if term.strip()]
    if not expected_terms:
        return MetricScore(
            dimension=EvaluationDimension.FACTUAL_GROUNDING,
            label="事实有据性",
            score=None,
            sample_count=0,
            detail="本样本未声明证据要求",
        )
    # Grounding must be based on caller-supplied evidence, never on the answer
    # repeating the expected term. Otherwise an unsupported answer can score
    # itself as its own source.
    evidence_text = " ".join(str(item).strip() for item in evidence if str(item).strip()).casefold()
    matched = sum(1 for term in expected_terms if term in evidence_text)
    score = matched / len(expected_terms)
    detail = f"证据要点命中 {matched}/{len(expected_terms)}"
    if not evidence_text:
        detail = "未提供可核验的显式证据"
    return MetricScore(
        dimension=EvaluationDimension.FACTUAL_GROUNDING,
        label="事实有据性",
        score=score,
        sample_count=1,
        numerator=matched,
        denominator=len(expected_terms),
        detail=detail,
    )


__all__ = ["grounding_score"]
