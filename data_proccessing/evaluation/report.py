"""Evaluation report writers."""

from __future__ import annotations

import json
from pathlib import Path


def write_evaluation_report(report: dict, output_dir: str | Path) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = report.get("metrics", {})
    lines = ["# Data Processing Evaluation", "", "| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {key} | {value:.4f} |" if isinstance(value, float) else f"| {key} | {value} |" for key, value in metrics.items())
    (path / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
