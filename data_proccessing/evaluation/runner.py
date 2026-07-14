"""Run the standalone processor against JSONL labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_proccessing.evaluation.metrics import calculate_metrics
from data_proccessing.evaluation.schema import EvaluationRecord
from data_proccessing.instrument_mapping.runtime import RuntimeLexicon
from data_proccessing.models import Document
from data_proccessing.pipeline.processor import process_document


def evaluate_dataset(dataset_path: str | Path, lexicon: RuntimeLexicon, *, skip_llm: bool = True) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line in Path(dataset_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = EvaluationRecord.from_dict(json.loads(line))
        text = record.raw_text
        if not text and Path(record.source_id).exists():
            text = Path(record.source_id).read_text(encoding="utf-8", errors="replace")
        result = process_document(
            Document(source_id=record.source_id, raw_text=text, title=Path(record.source_id).stem),
            lexicon,
            skip_llm=skip_llm,
        )
        candidates = [item for item in result.analyses if item.product_key == record.product_key]
        prediction = candidates[0] if candidates else (result.analyses[0] if result.analyses else None)
        predicted_product = bool(prediction)
        rows.append({
            "source_id": record.source_id,
            "product_correct": bool(prediction and prediction.product_key == record.product_key),
            "product_discovered": any(item.product_key == record.product_key for item in result.matches),
            "predicted_product": predicted_product,
            "direction_correct": bool(prediction and prediction.direction == record.direction),
            "method": prediction.method if prediction else None,
            "manual_review": bool(result.review_queue) or bool(prediction and prediction.need_manual_review),
            "duration_ms": result.processing_stats.get("duration_ms", 0),
        })
    return {"metrics": calculate_metrics(rows), "rows": rows}
