"""JSONL evaluation record schema."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    source_id: str
    product_key: str
    direction: str
    evidence: tuple[str, ...] = ()
    ambiguous: bool = False
    raw_text: str = ""

    @classmethod
    def from_dict(cls, row: dict) -> "EvaluationRecord":
        return cls(
            source_id=str(row["source_id"]),
            product_key=str(row["product_key"]),
            direction=str(row["direction"]),
            evidence=tuple(str(item) for item in row.get("evidence", [])),
            ambiguous=bool(row.get("ambiguous", False)),
            raw_text=str(row.get("raw_text", "")),
        )
