"""Portable candidate review queue helpers."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable, Mapping

from data_proccessing.instrument_mapping.models import AliasCandidate


def write_review_queue(candidates: Iterable[AliasCandidate], path: str | Path) -> int:
    rows = [candidate for candidate in candidates if candidate.status == "review_required"]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for candidate in rows:
            handle.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")
    return len(rows)


def read_review_decisions(path: str | Path) -> dict[str, dict[str, object]]:
    decisions: dict[str, dict[str, object]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        alias = str(row.get("normalized_alias") or row.get("raw_alias") or "")
        if alias:
            decisions[alias] = row
    return decisions


def approved_dynamic_aliases(decisions: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in decisions.values():
        if str(row.get("status") or "") != "approved":
            continue
        alias = str(row.get("raw_alias") or row.get("alias") or "").strip()
        key = str(row.get("product_key") or row.get("suggested_product_key") or "").strip()
        if alias and key:
            result[alias] = key
    return result
