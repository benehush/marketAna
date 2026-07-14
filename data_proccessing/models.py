"""Shared standalone data-processing models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Direction = Literal["看涨", "看跌", "中性"]
Decision = Literal["rule_accept", "llm_fallback", "manual_review", "no_signal"]
AnalysisMethod = Literal["rule", "llm", "manual"]


@dataclass(frozen=True, slots=True)
class Document:
    source_id: str
    raw_text: str
    title: str = ""
    file_name: str = ""
    file_type: str = "txt"
    metadata: dict[str, Any] = field(default_factory=dict)
    # These optional fields keep the standalone processor useful at the
    # integration boundary without making readers depend on the database.
    cleaned_text: str = ""
    source: str = ""
    company: str = ""
    publish_time: str | None = None


@dataclass(frozen=True, slots=True)
class DirectionSignal:
    signal_id: str
    product_key: str | None
    raw_alias: str
    direction: Direction
    signal_type: str
    phrase: str
    value: float | None
    confidence: float
    start: int
    end: int
    evidence_text: str
    context_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    evidence_id: str
    product_key: str
    quote: str
    raw_quote: str
    source: str
    start_char: int
    end_char: int
    match_type: str = "llm_candidate"


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    quote: str
    raw_quote: str
    source: str
    start_char: int
    end_char: int
    match_type: str
    validated: bool = True


@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    product_key: str
    display_name: str
    direction: Direction | None
    bullish_score: float
    bearish_score: float
    neutral_score: float
    margin: float
    confidence: float
    decision: Decision
    signals: tuple[DirectionSignal, ...] = ()
    evidence_snippets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    source_id: str
    product_key: str
    product: str
    direction: Direction | None
    reason: str
    confidence: float
    method: AnalysisMethod
    need_manual_review: bool = False
    evidence: tuple[str, ...] = ()
    evidence_excerpts: tuple[EvidenceExcerpt, ...] = ()
    processing_stats: dict[str, Any] = field(default_factory=dict)
    contract: str | None = None
    contract_key: str = ""


@dataclass(frozen=True, slots=True)
class ProcessingError:
    source_id: str
    stage: str
    error_type: str
    message: str
