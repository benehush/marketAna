"""Classification and routing metrics."""

from __future__ import annotations

from collections.abc import Iterable


def calculate_metrics(rows: Iterable[dict]) -> dict[str, float]:
    rows = list(rows)
    total = len(rows)
    if not total:
        return {"total": 0}
    product_correct = sum(bool(row.get("product_correct")) for row in rows)
    direction_correct = sum(bool(row.get("direction_correct")) for row in rows)
    discovered = sum(bool(row.get("product_discovered")) for row in rows)
    predicted = sum(bool(row.get("predicted_product")) for row in rows)
    rules = sum(row.get("method") == "rule" for row in rows)
    llm = sum(row.get("method") == "llm" for row in rows)
    manual = sum(bool(row.get("manual_review")) for row in rows)
    return {
        "total": total,
        "instrument_precision": product_correct / predicted if predicted else 0.0,
        "instrument_recall": discovered / total,
        "direction_accuracy": direction_correct / total,
        "rule_precision": sum(row.get("method") == "rule" and row.get("direction_correct") for row in rows) / rules if rules else 0.0,
        "rule_accept_rate": rules / total,
        "llm_fallback_rate": llm / total,
        "manual_review_rate": manual / total,
        "average_latency_ms": sum(float(row.get("duration_ms", 0)) for row in rows) / total,
    }
