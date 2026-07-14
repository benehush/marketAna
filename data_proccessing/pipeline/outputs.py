"""JSON/JSONL serialization for standalone pipeline results."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable

from data_proccessing.pipeline.processor import DocumentProcessingResult
from data_proccessing.pipeline.canonical import to_canonical_result


def write_results(results: Iterable[DocumentProcessingResult], output_dir: str | Path) -> dict[str, int]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result_rows: list[dict] = []
    evidence_rows: list[dict] = []
    review_rows: list[dict] = []
    canonical_rows: list[dict] = []
    report = {"documents": 0, "analyses": 0, "errors": 0, "reviews": 0, "rules": 0, "llm": 0}
    for item in results:
        report["documents"] += 1
        report["analyses"] += len(item.analyses)
        report["errors"] += len(item.errors)
        report["reviews"] += len(item.review_queue)
        for analysis in item.analyses:
            report["rules" if analysis.method == "rule" else "llm"] += 1
            result_rows.append(asdict(analysis))
        for signal in item.signals:
            evidence_rows.append(asdict(signal))
        review_rows.extend(item.review_queue)
        canonical_rows.append(to_canonical_result(item))
    _write_jsonl(output / "results.jsonl", result_rows)
    _write_jsonl(output / "evidence.jsonl", evidence_rows)
    _write_jsonl(output / "review_queue.jsonl", review_rows)
    _write_jsonl(output / "canonical_results.jsonl", canonical_rows)
    (output / "processing_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
