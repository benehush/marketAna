"""Build and export the instrument keyword lexicon."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from data_proccessing.instrument_mapping.discovery import InstrumentDiscoverer
from data_proccessing.instrument_mapping.models import (
    AliasCandidate,
    BuildConfig,
    CandidateEvidence,
    CandidateStatus,
    Document,
    InstrumentLexiconEntry,
    LexiconBuildResult,
    SeedInstrument,
)
from data_proccessing.instrument_mapping.progress import ProgressCallback
from data_proccessing.instrument_mapping.seed_catalog import (
    NEGATIVE_CONTEXTS_BY_KEY,
    load_seed_instruments,
    normalize_alias,
)


SEED_EVIDENCE_COUNT = 1
HIGH_VALUE_EVIDENCE = {"contract_code", "bracket_heading", "label_field", "catalog_alias", "title_symbol"}
SHAPE_EVIDENCE = {"contract_code", "suffix_pattern", "symbol_context", "title_symbol", "ocr_split_symbol"}
CONTEXT_EVIDENCE = {"market_context", "symbol_context", "ocr_split_symbol"}
CATALOG_EVIDENCE = {"catalog_alias", "contract_code", "symbol_context", "title_symbol", "ocr_split_symbol"}
FUTURES_CONTEXT_EVIDENCE = {"contract_code", "suffix_pattern", "symbol_context", "ocr_split_symbol", "market_context"}
UNLINKED_REVIEW_ANCHOR_EVIDENCE = {
    "bracket_heading",
    "label_field",
    "title_symbol",
    "contract_code",
    "symbol_context",
    "ocr_split_symbol",
    "market_context",
}


def build_instrument_lexicon(
    documents: list[Document] | tuple[Document, ...],
    config: BuildConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> LexiconBuildResult:
    config = config or BuildConfig()
    seeds = load_seed_instruments()
    if progress_callback:
        progress_callback("load seeds", 1, 1, f"{len(seeds)} instruments")
    discoverer = InstrumentDiscoverer(seeds, config=config)
    evidence_by_alias = discoverer.discover(documents, progress_callback=progress_callback)
    candidates = _classify_candidates(evidence_by_alias, seeds, config, progress_callback=progress_callback)
    lexicon = _build_lexicon(seeds, candidates, progress_callback=progress_callback)
    report = _build_report(documents, lexicon, candidates)
    if progress_callback:
        progress_callback("report", 1, 1, f"{len(candidates)} candidates")
    return LexiconBuildResult(lexicon=lexicon, candidates=candidates, report=report)


def write_build_artifacts(
    result: LexiconBuildResult,
    output_dir: str | Path,
    *,
    progress_callback: ProgressCallback | None = None,
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    lexicon_payload = [asdict(item) for item in result.lexicon]
    (output_path / "instrument_lexicon.json").write_text(
        json.dumps(lexicon_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if progress_callback:
        progress_callback("write artifacts", 1, 3, "instrument_lexicon.json")

    with (output_path / "alias_candidates.jsonl").open("w", encoding="utf-8") as handle:
        for candidate in result.candidates:
            handle.write(json.dumps(asdict(candidate), ensure_ascii=True, sort_keys=True) + "\n")
    if progress_callback:
        progress_callback("write artifacts", 2, 3, "alias_candidates.jsonl")

    with (output_path / "review_queue.jsonl").open("w", encoding="utf-8") as handle:
        for candidate in result.candidates:
            if candidate.status == "review_required":
                handle.write(json.dumps(asdict(candidate), ensure_ascii=False, sort_keys=True) + "\n")

    (output_path / "build_report.json").write_text(
        json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if progress_callback:
        progress_callback("write artifacts", 3, 3, "build_report.json")


def _classify_candidates(
    evidence_by_alias: dict[str, CandidateEvidence],
    seeds: tuple[SeedInstrument, ...],
    config: BuildConfig,
    progress_callback: ProgressCallback | None = None,
) -> tuple[AliasCandidate, ...]:
    seed_alias_keys = {
        normalize_alias(alias): item.product_key
        for item in seeds
        for alias in item.seed_aliases
        if normalize_alias(alias)
    }
    candidates: list[AliasCandidate] = []
    total = len(evidence_by_alias)
    for index, (normalized_alias, evidence) in enumerate(evidence_by_alias.items(), start=1):
        score = _score_candidate(evidence)
        suggested_key = _suggest_product_key(evidence, seed_alias_keys)
        status = _candidate_status(
            evidence=evidence,
            normalized_alias=normalized_alias,
            suggested_key=suggested_key,
            seed_alias_keys=seed_alias_keys,
            score=score,
            config=config,
        )
        candidates.append(
            AliasCandidate(
                raw_alias=evidence.raw_alias,
                normalized_alias=normalized_alias,
                status=status,
                score=round(score, 3),
                suggested_product_key=suggested_key,
                occurrence_count=evidence.occurrence_count,
                document_count=len(evidence.document_ids),
                evidence_types=tuple(sorted(evidence.evidence_types)),
                evidence_snippets=tuple(evidence.evidence_snippets),
                source_docs=tuple(evidence.source_docs),
                negative_reasons=tuple(sorted(evidence.negative_reasons)),
            )
        )
        if progress_callback:
            progress_callback("classify", index, total, evidence.raw_alias)
    return tuple(sorted(candidates, key=lambda item: (_status_rank(item.status), -item.score, item.raw_alias)))


def _build_lexicon(
    seeds: tuple[SeedInstrument, ...],
    candidates: tuple[AliasCandidate, ...],
    progress_callback: ProgressCallback | None = None,
) -> tuple[InstrumentLexiconEntry, ...]:
    aliases_by_key: dict[str, set[str]] = {item.product_key: set(item.seed_aliases) for item in seeds}
    evidence_counts: dict[str, int] = {item.product_key: SEED_EVIDENCE_COUNT for item in seeds}
    confidence_by_key: dict[str, float] = {item.product_key: 1.0 for item in seeds}

    for candidate in candidates:
        if candidate.status not in {"approved_seed", "auto_approved"} or not candidate.suggested_product_key:
            continue
        aliases_by_key.setdefault(candidate.suggested_product_key, set()).add(candidate.raw_alias)
        evidence_counts[candidate.suggested_product_key] = evidence_counts.get(candidate.suggested_product_key, 0) + candidate.occurrence_count
        confidence_by_key[candidate.suggested_product_key] = max(
            confidence_by_key.get(candidate.suggested_product_key, 0.0),
            candidate.score,
        )

    entries: list[InstrumentLexiconEntry] = []
    total = len(seeds)
    for index, item in enumerate(seeds, start=1):
        aliases = tuple(sorted(aliases_by_key.get(item.product_key, set()), key=lambda alias: (len(alias), alias)))
        contract_patterns = _contract_patterns(item)
        entries.append(
            InstrumentLexiconEntry(
                product_key=item.product_key,
                canonical=item.canonical,
                official_name=item.official_name,
                exchange=item.exchange,
                symbol=item.symbol,
                group=item.group,
                aliases=aliases,
                contract_patterns=contract_patterns,
                negative_contexts=NEGATIVE_CONTEXTS_BY_KEY.get(item.product_key, ()),
                confidence=round(confidence_by_key.get(item.product_key, 1.0), 3),
                evidence_count=evidence_counts.get(item.product_key, 0),
            )
        )
        if progress_callback:
            progress_callback("build lexicon", index, total, item.canonical)
    return tuple(entries)


def _score_candidate(evidence: CandidateEvidence) -> float:
    if evidence.negative_reasons and evidence.occurrence_count == 0:
        return 0.0

    score = 0.0
    if evidence.evidence_types & HIGH_VALUE_EVIDENCE:
        score += 0.44
    if evidence.evidence_types & SHAPE_EVIDENCE:
        score += 0.22
    if evidence.evidence_types & CATALOG_EVIDENCE:
        score += 0.24
    if evidence.evidence_types & CONTEXT_EVIDENCE:
        score += 0.18
    if evidence.document_ids:
        score += min(0.12, len(evidence.document_ids) * 0.04)
    if evidence.occurrence_count >= 3:
        score += 0.05
    if len(evidence.suggested_product_keys) > 1:
        score -= 0.28
    if evidence.negative_reasons:
        score -= 0.5
    triangle = sum(
        1
        for evidence_group in (SHAPE_EVIDENCE, CATALOG_EVIDENCE, CONTEXT_EVIDENCE)
        if evidence.evidence_types & evidence_group
    )
    if triangle < 2 and evidence.normalized_alias not in {normalize_alias(evidence.raw_alias)}:
        score -= 0.08
    if triangle < 2 and "bracket_heading" not in evidence.evidence_types and "label_field" not in evidence.evidence_types:
        score = min(score, 0.55)
    return max(0.0, min(1.0, score))


def _suggest_product_key(evidence: CandidateEvidence, seed_alias_keys: dict[str, str]) -> str | None:
    if evidence.normalized_alias in seed_alias_keys:
        return seed_alias_keys[evidence.normalized_alias]
    if len(evidence.suggested_product_keys) == 1:
        return next(iter(evidence.suggested_product_keys))
    return None


def _candidate_status(
    *,
    evidence: CandidateEvidence,
    normalized_alias: str,
    suggested_key: str | None,
    seed_alias_keys: dict[str, str],
    score: float,
    config: BuildConfig,
) -> CandidateStatus:
    if evidence.negative_reasons and evidence.occurrence_count == 0:
        return "rejected"
    if evidence.negative_reasons and score < config.review_threshold:
        return "rejected"
    if normalized_alias in seed_alias_keys and suggested_key:
        return "approved_seed"
    if suggested_key and _evidence_class_count(evidence) >= 2 and score >= config.auto_approve_threshold:
        return "auto_approved"
    if suggested_key and score >= config.review_threshold:
        return "review_required"
    if suggested_key is None and not _is_reviewable_unlinked_candidate(evidence):
        return "rejected"
    if score >= config.review_threshold:
        return "review_required"
    return "rejected"


def _evidence_class_count(evidence: CandidateEvidence) -> int:
    return sum(
        bool(evidence.evidence_types & evidence_group)
        for evidence_group in (SHAPE_EVIDENCE, CATALOG_EVIDENCE, CONTEXT_EVIDENCE)
    )


def _is_reviewable_unlinked_candidate(evidence: CandidateEvidence) -> bool:
    alias = evidence.raw_alias
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", alias):
        return False
    if re.fullmatch(r"\d+", alias):
        return False
    chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in alias)
    ascii_letter_count = sum(char.isascii() and char.isalpha() for char in alias)
    if chinese_count == 0 and ascii_letter_count < 2:
        return False
    has_futures_context = bool(evidence.evidence_types & FUTURES_CONTEXT_EVIDENCE)
    has_non_suffix_anchor = bool(evidence.evidence_types & UNLINKED_REVIEW_ANCHOR_EVIDENCE)
    return has_futures_context and has_non_suffix_anchor and len(evidence.document_ids) >= 2


def _contract_patterns(item: SeedInstrument) -> tuple[str, ...]:
    if not item.symbol:
        return ()
    symbol = item.symbol.upper()
    return (
        rf"(?<![A-Za-z0-9]){symbol}\d{{2,4}}(?![A-Za-z0-9])",
        rf"(?<![A-Za-z0-9]){symbol}\s*\d{{2,4}}\s*合约",
    )


def _build_report(
    documents: list[Document] | tuple[Document, ...],
    lexicon: tuple[InstrumentLexiconEntry, ...],
    candidates: tuple[AliasCandidate, ...],
) -> dict[str, object]:
    by_status: dict[str, int] = {}
    for candidate in candidates:
        by_status[candidate.status] = by_status.get(candidate.status, 0) + 1
    return {
        "_comment": {
            "documents": "本次构建处理的文档总数",
            "lexicon_entries": "最终词条数（已收录的品种别名分组）",
            "candidate_count": "所有候选别名总数",
            "status_counts": "各状态候选别名数量分布",
            "approved_seed_aliases": "来自种子库、直接通过的别名数（seed approved）",
            "auto_approved_aliases": "自动阈值通过（无需人工审查）的别名数",
            "review_required_aliases": "需要人工审查的别名数",
            "rejected_aliases": "被拒绝的别名数",
            "top_review_required": "需要人工审查的前 20 条候选别名详情",
        },
        "documents": len(documents),
        "lexicon_entries": len(lexicon),
        "candidate_count": len(candidates),
        "status_counts": by_status,
        "approved_seed_aliases": by_status.get("approved_seed", 0),
        "auto_approved_aliases": by_status.get("auto_approved", 0),
        "review_required_aliases": by_status.get("review_required", 0),
        "rejected_aliases": by_status.get("rejected", 0),
        "top_review_required": [
            {
                "raw_alias": candidate.raw_alias,
                "suggested_product_key": candidate.suggested_product_key,
                "score": candidate.score,
                "evidence_types": candidate.evidence_types,
            }
            for candidate in candidates
            if candidate.status == "review_required"
        ][:20],
    }


def _status_rank(status: str) -> int:
    return {
        "approved_seed": 0,
        "auto_approved": 1,
        "review_required": 2,
        "rejected": 3,
    }.get(status, 9)
