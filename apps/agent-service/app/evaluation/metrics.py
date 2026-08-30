"""可解释的确定性评测指标编排层。

具体指标按职责拆分到相邻模块；本模块保留稳定入口，避免调用方感知内部
实现变化。指标不伪造模型 usage，缺失的质量标注会返回 ``score=None``。
"""

from __future__ import annotations

from . import metrics_primitives as _primitives
from . import metrics_security as _security
from .metrics_grounding import grounding_score as _grounding_score
from .models import EvaluationCase, EvaluationDimension, EvaluationRunRequest, MetricScore

# Keep the former module-level names available for integrations that imported
# helpers before the implementation was split into focused modules.
_TOKEN_RE = _primitives._TOKEN_RE
_binary_score = _primitives.binary_score
_consistency_score = _primitives.consistency_score
estimate_tokens = _primitives.estimate_tokens
_jaccard = _primitives.jaccard
_keyword_score = _primitives.keyword_score
_measurement_score = _primitives.measurement_score
_tokens = _primitives.tokens
_tool_score = _primitives.tool_score
_INJECTION_RE = _security._INJECTION_RE
_REFUSAL_RE = _security._REFUSAL_RE
_SECRET_RE = _security._SECRET_RE
_SENSITIVE_LEAK_RE = _security._SENSITIVE_LEAK_RE
_injection_score = _security.injection_score
looks_like_prompt_injection = _security.looks_like_prompt_injection
looks_like_safe_refusal = _security.looks_like_safe_refusal


def score_run(
    request: EvaluationRunRequest,
    case: EvaluationCase | None,
    *,
    input_price_per_1k: float,
    output_price_per_1k: float,
    currency: str,
) -> tuple[dict[EvaluationDimension, MetricScore], int, int, float]:
    """计算单次评测的所有可解释指标。

    输入标注优先于数据集案例标注；没有案例时，只有明确传入的注入信号或
    可检测的注入文本会参与安全维度评测。
    """

    expected_tools = request.expected_tools if request.expected_tools is not None else (case.expected_tools if case else [])
    expected_keywords = (
        request.expected_keywords if request.expected_keywords is not None else (case.expected_keywords if case else [])
    )
    expected_evidence = (
        request.expected_evidence if request.expected_evidence is not None else (case.expected_evidence if case else [])
    )
    injection_attempt = (
        request.injection_attempt
        if request.injection_attempt is not None
        else bool(case and case.injection_attempt)
    )
    if request.injection_attempt is None and case is None:
        injection_attempt = looks_like_prompt_injection(request.input_text)
    expected_blocked = bool(case and case.expected_blocked)
    input_tokens = request.input_tokens if request.input_tokens is not None else estimate_tokens(request.input_text)
    output_tokens = request.output_tokens if request.output_tokens is not None else estimate_tokens(request.output_text)
    cost = round((input_tokens * input_price_per_1k + output_tokens * output_price_per_1k) / 1000, 8)

    scores: dict[EvaluationDimension, MetricScore] = {
        EvaluationDimension.TOKEN_USAGE: MetricScore(
            dimension=EvaluationDimension.TOKEN_USAGE,
            label="Token 消耗",
            score=None,
            sample_count=1,
            numerator=input_tokens + output_tokens,
            denominator=None,
            detail=f"输入 {input_tokens}，输出 {output_tokens}，币种 {currency}",
        ),
        EvaluationDimension.COST: MetricScore(
            dimension=EvaluationDimension.COST,
            label="预估价格",
            score=None,
            sample_count=1,
            numerator=cost,
            detail=f"按输入 {input_price_per_1k:g}/1K、输出 {output_price_per_1k:g}/1K 计算",
        ),
        EvaluationDimension.AGENT_LATENCY: _measurement_score(
            EvaluationDimension.AGENT_LATENCY, "Agent 延迟", request.agent_latency_ms
        ),
        EvaluationDimension.DIGITAL_HUMAN_LATENCY: _measurement_score(
            EvaluationDimension.DIGITAL_HUMAN_LATENCY, "数字人延迟", request.digital_human_latency_ms
        ),
        EvaluationDimension.FIRST_EVENT_LATENCY: _measurement_score(
            EvaluationDimension.FIRST_EVENT_LATENCY, "首事件延迟", request.first_event_latency_ms
        ),
        EvaluationDimension.FIRST_VISIBLE_LATENCY: _measurement_score(
            EvaluationDimension.FIRST_VISIBLE_LATENCY, "首可见内容延迟", request.first_visible_latency_ms
        ),
        EvaluationDimension.CANCELLATION_LATENCY: _measurement_score(
            EvaluationDimension.CANCELLATION_LATENCY, "取消生效延迟", request.cancellation_latency_ms
        ),
        EvaluationDimension.TASK_SUCCESS: _binary_score(
            EvaluationDimension.TASK_SUCCESS,
            "任务成功率",
            request.task_success
            if request.task_success is not None
            else request.status == "success",
        ),
        EvaluationDimension.TOOL_CALL_ACCURACY: _tool_score(expected_tools, request.actual_tools),
        EvaluationDimension.RESULT_CORRECTNESS: _keyword_score(
            EvaluationDimension.RESULT_CORRECTNESS, "结果正确率", request.output_text, expected_keywords
        ),
        EvaluationDimension.RESULT_CONSISTENCY: _consistency_score(request.output_text, request.comparison_outputs),
        EvaluationDimension.FACTUAL_GROUNDING: _grounding_score(
            request.output_text, request.evidence, expected_evidence
        ),
        EvaluationDimension.PROMPT_INJECTION_DEFENSE: _injection_score(
            request.output_text, injection_attempt, request.injection_blocked, expected_blocked
        ),
    }
    return scores, input_tokens, output_tokens, cost


__all__ = ["estimate_tokens", "score_run", "looks_like_prompt_injection", "looks_like_safe_refusal"]
