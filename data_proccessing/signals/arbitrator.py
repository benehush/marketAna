"""Explainable weighted vote for direction signals."""

from __future__ import annotations

from collections.abc import Iterable

from data_proccessing.catalog import get_product
from data_proccessing.config import ProcessingConfig
from data_proccessing.models import ArbitrationResult, DirectionSignal
from data_proccessing.signals.context import context_factor
from data_proccessing.signals.patterns import PATTERN_WEIGHTS


def arbitrate(
    product_key: str,
    signals: Iterable[DirectionSignal],
    *,
    config: ProcessingConfig | None = None,
) -> ArbitrationResult:
    config = config or ProcessingConfig()
    selected = tuple(signals)
    scores = {"看涨": 0.0, "看跌": 0.0, "中性": 0.0}
    for signal in selected:
        base = PATTERN_WEIGHTS.get(signal.signal_type, 0.4)
        score = base * signal.confidence * context_factor(signal.context_flags)
        scores[signal.direction] += score
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    winner, winner_score = ranked[0]
    second_score = ranked[1][1]
    margin = winner_score - second_score
    total = sum(scores.values())
    confidence = min(1.0, max(0.0, (winner_score / total if total else 0.0) + min(margin, 1.0) * 0.15))
    strong_conflict = scores["看涨"] >= 0.75 and scores["看跌"] >= 0.75 and margin < 1.0
    if not selected:
        decision = "no_signal"
        direction = None
    elif strong_conflict:
        decision = "llm_fallback"
        direction = None
    elif winner_score >= 1.50 and margin >= 0.50:
        decision = "rule_accept"
        direction = winner  # type: ignore[assignment]
    elif margin >= config.llm_fallback_margin:
        decision = "rule_accept"
        direction = winner  # type: ignore[assignment]
    else:
        decision = "llm_fallback"
        direction = None
    product = get_product(product_key)
    display_name = product.display_name if product else product_key
    evidence = tuple(dict.fromkeys(signal.evidence_text for signal in selected))[:5]
    return ArbitrationResult(
        product_key=product_key,
        display_name=display_name,
        direction=direction,  # type: ignore[arg-type]
        bullish_score=round(scores["看涨"], 4),
        bearish_score=round(scores["看跌"], 4),
        neutral_score=round(scores["中性"], 4),
        margin=round(margin, 4),
        confidence=round(confidence, 4),
        decision=decision,
        signals=selected,
        evidence_snippets=evidence,
    )
