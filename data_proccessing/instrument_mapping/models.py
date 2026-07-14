"""Data models for guided instrument alias discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


CandidateStatus = Literal["approved_seed", "auto_approved", "review_required", "rejected"]


@dataclass(frozen=True, slots=True)
class Document:
    """Raw source text used by the discovery pass."""

    source_id: str
    raw_text: str
    title: str = ""
    file_name: str = ""


@dataclass(frozen=True, slots=True)
class BuildConfig:
    """Tunable thresholds and output settings."""

    auto_approve_threshold: float = 0.72
    review_threshold: float = 0.35
    max_snippets_per_candidate: int = 3
    max_source_docs_per_candidate: int = 8
    context_window: int = 36


@dataclass(frozen=True, slots=True)
class SeedInstrument:
    product_key: str
    canonical: str
    official_name: str
    exchange: str
    symbol: str
    group: str
    seed_aliases: tuple[str, ...]


@dataclass(slots=True)
class CandidateEvidence:
    raw_alias: str
    normalized_alias: str
    suggested_product_keys: set[str] = field(default_factory=set)
    occurrence_count: int = 0
    document_ids: set[str] = field(default_factory=set)
    evidence_types: set[str] = field(default_factory=set)
    source_docs: list[str] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    negative_reasons: set[str] = field(default_factory=set)

    def add_occurrence(
        self,
        *,
        source_id: str,
        snippet: str,
        evidence_type: str,
        product_key: str | None,
        config: BuildConfig,
    ) -> None:
        self.occurrence_count += 1
        self.document_ids.add(source_id)
        self.evidence_types.add(evidence_type)
        if product_key:
            self.suggested_product_keys.add(product_key)
        if source_id not in self.source_docs and len(self.source_docs) < config.max_source_docs_per_candidate:
            self.source_docs.append(source_id)
        snippet = " ".join(snippet.split())
        if snippet and snippet not in self.evidence_snippets and len(self.evidence_snippets) < config.max_snippets_per_candidate:
            self.evidence_snippets.append(snippet)


@dataclass(frozen=True, slots=True)
class AliasCandidate:
    raw_alias: str
    normalized_alias: str
    status: CandidateStatus
    score: float
    suggested_product_key: str | None
    occurrence_count: int
    document_count: int
    evidence_types: tuple[str, ...]
    evidence_snippets: tuple[str, ...]
    source_docs: tuple[str, ...]
    negative_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InstrumentLexiconEntry:
    product_key: str
    canonical: str
    official_name: str
    exchange: str
    symbol: str
    group: str
    aliases: tuple[str, ...]
    contract_patterns: tuple[str, ...]
    negative_contexts: tuple[str, ...]
    confidence: float
    evidence_count: int


@dataclass(frozen=True, slots=True)
class LexiconBuildResult:
    lexicon: tuple[InstrumentLexiconEntry, ...]
    candidates: tuple[AliasCandidate, ...]
    report: dict[str, object]

    def write_to(self, output_dir: str | Path) -> None:
        from data_proccessing.instrument_mapping.builder import write_build_artifacts

        write_build_artifacts(self, output_dir)

