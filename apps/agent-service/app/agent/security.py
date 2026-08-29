"""安全门策略：在任何模型、RAG 或工具调用前识别明显的提示词注入。"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import IntentDecision, IntentName, IntentSource, ToolRoutePlan


@dataclass(frozen=True, slots=True)
class InjectionAssessment:
    """对一条用户输入的最小安全判定，不保存原始敏感文本。"""

    attempted: bool
    reason_code: str | None = None


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"(?:忽略|无视|绕过|跳过).{0,40}(?:系统|开发者|之前|安全|指令|规则|确认)|"
            r"(?:ignore|disregard|bypass|override|skip).{0,60}(?:system|developer|instruction|safety|rule|confirmation)",
            re.IGNORECASE,
        ),
    ),
    (
        "reveal_internal_prompt",
        re.compile(
            r"(?:输出|泄露|打印|显示|告诉我|给出).{0,30}(?:隐藏提示词|系统提示词|开发者消息|内部指令|system prompt|developer message)|"
            r"(?:reveal|show|print|dump|tell me).{0,40}(?:system prompt|developer message|hidden instruction|internal prompt)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltrate_credentials",
        re.compile(
            r"(?:输出|泄露|打印|显示|告诉我|给出).{0,30}(?:token|密钥|apikey|api key|secret|密码|凭据)|"
            r"(?:reveal|show|print|dump|exfiltrate).{0,40}(?:token|api[_ -]?key|secret|password|credential)",
            re.IGNORECASE,
        ),
    ),
    (
        "bypass_authorization",
        re.compile(
            r"(?:绕过|跳过|无需|不需要).{0,24}(?:确认|授权|权限|审批)|"
            r"(?:without|skip|bypass).{0,36}(?:confirmation|authorization|permission|approval)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_injection",
        re.compile(r"(?:^|\n)\s*(?:<\/?(?:system|developer|assistant)>|#{2,}\s*(?:system|developer))", re.IGNORECASE),
    ),
    ("jailbreak_marker", re.compile(r"\b(?:jailbreak|dan mode|do anything now)\b", re.IGNORECASE)),
)


def assess_prompt_injection(text: str) -> InjectionAssessment:
    """返回可审计的原因码；未命中时不保留输入内容。"""

    normalized = " ".join(text.strip().split())
    for reason_code, pattern in _PATTERNS:
        if pattern.search(normalized):
            return InjectionAssessment(attempted=True, reason_code=reason_code)
    return InjectionAssessment(attempted=False)


def blocked_decision() -> IntentDecision:
    """为被安全门拦截的请求构造不触发模型/工具的意图结果。"""

    return IntentDecision(
        name=IntentName.UNKNOWN,
        confidence=1.0,
        source=IntentSource.RULE,
        rationale="命中提示词注入安全策略",
    )


def blocked_plan() -> ToolRoutePlan:
    """安全门命中后不披露、不执行任何 MCP 工具。"""

    return ToolRoutePlan(
        intent=IntentName.UNKNOWN,
        confidence=1.0,
        disclosure_level="summary",
        category=None,
        disclosed_tools=[],
        selected_tools=[],
        rationale="安全策略拦截，跳过 RAG 与工具调用",
    )


def safe_refusal() -> str:
    """固定、短且不包含密钥关键词的用户可见拒答。"""

    return "这个请求涉及绕过安全规则或访问内部信息，我不能执行。可以继续处理经过授权的正常任务。"


def reason_label(reason_code: str | None) -> str:
    """将内部原因码转换为前端可读的短说明。"""

    return {
        "override_instructions": "尝试覆盖系统指令",
        "reveal_internal_prompt": "尝试索取内部提示",
        "exfiltrate_credentials": "尝试索取凭据",
        "bypass_authorization": "尝试绕过授权确认",
        "role_injection": "检测到伪造角色标记",
        "jailbreak_marker": "检测到越权模式标记",
    }.get(reason_code or "", "命中安全策略")


__all__ = [
    "InjectionAssessment",
    "assess_prompt_injection",
    "blocked_decision",
    "blocked_plan",
    "reason_label",
    "safe_refusal",
]
