"""Context flags that prevent naive keyword voting."""

from __future__ import annotations


NEGATION_WORDS = ("不", "未", "没有", "并非", "难以", "尚未", "未见")
CONDITIONAL_WORDS = ("若", "如果", "一旦", "除非", "在……情况下", "假设")
HISTORICAL_WORDS = ("昨日", "此前", "过去", "前期", "上周", "此前一度")
RISK_WORDS = ("风险", "警惕", "压力", "承压", "不排除")
TURN_WORDS = ("但", "然而", "不过", "转为", "随后")


def context_flags(text: str, start: int, end: int) -> tuple[str, ...]:
    prefix = text[max(0, start - 30):start]
    suffix = text[end:min(len(text), end + 30)]
    around = prefix + suffix
    flags: list[str] = []
    if any(word in prefix[-8:] for word in NEGATION_WORDS):
        flags.append("negated")
    if any(word in prefix[-15:] for word in CONDITIONAL_WORDS):
        flags.append("conditional")
    if any(word in prefix[-15:] for word in HISTORICAL_WORDS):
        flags.append("historical")
    if any(word in around for word in RISK_WORDS):
        flags.append("risk_context")
    if any(word in prefix[-12:] for word in TURN_WORDS):
        flags.append("after_turn")
    return tuple(flags)


def context_factor(flags: tuple[str, ...]) -> float:
    factor = 1.0
    if "negated" in flags:
        factor *= 0.25
    if "conditional" in flags:
        factor *= 0.65
    if "historical" in flags:
        factor *= 0.45
    if "risk_context" in flags:
        factor *= 0.70
    if "after_turn" in flags:
        factor *= 0.75
    return factor
