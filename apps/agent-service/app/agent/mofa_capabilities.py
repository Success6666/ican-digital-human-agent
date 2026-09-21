"""Official Mofa Xingyun action intents and emotion labels."""

from __future__ import annotations

from typing import Any

MOFA_EMOTIONS = (
    "happy",
    "sad",
    "angry",
    "surprised",
    "neutral",
)

MOFA_ACTION_INTENT_OPTIONS = (
    ("FistSalute", "拱手示意礼节"),
    ("ClapHands", "鼓掌"),
    ("Welcome", "欢迎"),
    ("ThankYou", "感谢"),
    ("Prohibit", "禁止"),
    ("KeyPoints", "抓重点"),
    ("Stable", "保持稳定"),
    ("Comfort", "安抚"),
    ("Downsize", "缩减空间"),
    ("Cuttime", "缩减时间"),
    ("Extendsize", "扩大空间"),
    ("Extendtime", "拉长时间"),
    ("Elevate", "提升"),
    ("Like", "点赞"),
    ("Goodbye", "再见"),
    ("Hello", "打招呼"),
    ("PointingSelf", "指自己"),
    ("Surprise", "惊喜"),
    ("Pointscreen", "指屏幕"),
    ("Wish", "许愿"),
    ("Heart", "比心"),
    ("PointAudience", "指观众"),
    ("Downward", "降低"),
    ("Click", "点击"),
    ("Encourage", "鼓舞激励"),
    ("Wave", "波动"),
    ("Up", "上"),
    ("Down", "下"),
    ("Left", "左"),
    ("Right", "右"),
    ("Forward", "前"),
    ("Backward", "后"),
    ("Center", "中"),
    ("Near", "近"),
    ("Far", "远"),
    ("Large", "大"),
    ("Small", "小"),
    ("High", "高"),
    ("Low", "低"),
    ("Partial", "局部"),
    ("Whole", "整体"),
    ("Edge", "边缘"),
    ("Apologize", "道歉"),
    ("Approve", "认可"),
    ("Pause", "暂停"),
    ("Expect", "期待"),
    ("Think", "思考"),
    ("Confused", "困惑"),
    ("Indifferent", "无所谓"),
    ("Ecstasy", "狂喜"),
    ("Joyful", "愉快"),
    ("Playful", "调皮"),
    ("Dissatisfied", "不满"),
    ("Reject", "排斥"),
    ("Worry", "担心"),
    ("Disappointed", "失望"),
    ("Aggrieved", "委屈"),
    ("Shakehands", "握手"),
    ("Highfive", "击掌"),
    ("Curious", "好奇"),
    ("Worship", "崇拜"),
    ("Shy", "害羞"),
    ("Scared", "害怕"),
    ("Tired", "疲惫"),
    ("Surprised", "惊讶"),
    ("Nauseous", "恶心"),
    ("Ill", "生病"),
    ("Dance", "跳舞"),
    ("Scan", "扫描"),
    ("Sos", "紧急"),
)

MOFA_ACTION_INTENTS = tuple(name for name, _ in MOFA_ACTION_INTENT_OPTIONS)

_EMOTION_BY_KEY = {item.casefold(): item for item in MOFA_EMOTIONS}
_ACTION_BY_KEY = {item.casefold(): item for item in MOFA_ACTION_INTENTS}
_INTERNAL_EXPRESSION_EMOTIONS = {
    "relieved": "happy",
    "listening": "neutral",
    "thinking": "neutral",
    "speaking": "neutral",
    "acknowledging": "neutral",
    "interrupted": "neutral",
}


def normalize_mofa_emotion(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _EMOTION_BY_KEY.get(value.strip().casefold())


def normalize_mofa_action_intent(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _ACTION_BY_KEY.get(value.strip().casefold())


def mofa_emotion_for_expression(value: Any) -> str:
    official = normalize_mofa_emotion(value)
    if official:
        return official
    key = value.strip().casefold() if isinstance(value, str) else ""
    return _INTERNAL_EXPRESSION_EMOTIONS.get(key, "neutral")


__all__ = [
    "MOFA_ACTION_INTENTS",
    "MOFA_ACTION_INTENT_OPTIONS",
    "MOFA_EMOTIONS",
    "mofa_emotion_for_expression",
    "normalize_mofa_action_intent",
    "normalize_mofa_emotion",
]
