"""Single-document standalone processing pipeline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
import time
from typing import Any

from data_proccessing.config import ProcessingConfig
from data_proccessing.instrument_mapping.runtime import LexiconMatch, RuntimeLexicon
from data_proccessing.llm.client import LLMCallResult, LLMClient, LLMRequestError
from data_proccessing.llm.context import build_llm_context, build_llm_correction_context
from data_proccessing.llm.diagnostics import sanitize_text
from data_proccessing.llm.parser import LLMParseError, parse_llm_response
from data_proccessing.models import (
    AnalysisResult,
    DirectionSignal,
    Document,
    EvidenceCandidate,
    EvidenceExcerpt,
)
from data_proccessing.pipeline.canonical import build_evidence_candidates, build_product_evidence
from data_proccessing.sections import (
    ProductSection,
    build_product_sections,
    is_related_mention_only,
    section_for_position,
)
from data_proccessing.signals.aggregator import aggregate_signals
from data_proccessing.signals.arbitrator import arbitrate
from data_proccessing.signals.extractor import extract_signals


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    document: Document
    matches: tuple[LexiconMatch, ...]
    signals: tuple[DirectionSignal, ...]
    analyses: tuple[AnalysisResult, ...]
    review_queue: tuple[dict[str, Any], ...] = ()
    errors: tuple[dict[str, Any], ...] = ()
    processing_stats: dict[str, Any] = field(default_factory=dict)


def process_document(
    document: Document,
    lexicon: RuntimeLexicon,
    *,
    llm_client: LLMClient | None = None,
    config: ProcessingConfig | None = None,
    skip_llm: bool = False,
) -> DocumentProcessingResult:
    config = config or ProcessingConfig()
    started = time.perf_counter()
    matches = tuple(lexicon.find_matches(document.raw_text, title=document.title))
    sections = build_product_sections(document.raw_text, matches)
    signals = tuple(extract_signals(document.raw_text, matches, context_window=config.context_window))
    grouped = aggregate_signals(signals)
    analyses: list[AnalysisResult] = []
    review_queue: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    rule_count = 0
    llm_count = 0
    llm_retry_count = 0
    llm_recovered_count = 0
    llm_error_types: Counter[str] = Counter()
    for product_key, product_signals in grouped.items():
        arbitration = arbitrate(product_key, product_signals, config=config)
        rule_candidate: AnalysisResult | None = None
        fallback_reason = "rule_uncertain"
        if arbitration.decision == "rule_accept":
            rule_count += 1
            rule_evidence = _quality_evidence(
                document,
                product_key=product_key,
                direction=arbitration.direction,
                signals=signals,
                matches=matches,
            )
            rule_candidate = _rule_result(
                document,
                arbitration,
                evidence=_evidence_quotes(rule_evidence),
                need_manual_review=not rule_evidence["excerpts"],
            )
            if rule_evidence["excerpts"]:
                analyses.append(rule_candidate)
                continue
            fallback_reason = "rule_evidence_quality_failed"
        if arbitration.decision == "no_signal":
            no_signal_evidence = _quality_evidence(
                document,
                product_key=product_key,
                direction=None,
                signals=signals,
                matches=matches,
                allow_cross_product=True,
            )
            review_queue.append(
                {
                    "source_id": document.source_id,
                    "product_key": product_key,
                    "product": arbitration.display_name,
                    "reason": "no_signal",
                    "evidence": no_signal_evidence,
                }
            )
            continue

        llm_candidates = build_evidence_candidates(
            product_key=product_key,
            raw_text=document.raw_text,
            matches=matches,
            max_candidates=config.max_llm_snippets,
            max_chars=config.max_llm_chars,
        )
        if skip_llm or llm_client is None:
            if rule_candidate is not None:
                analyses.append(rule_candidate)
            review_queue.append({
                "source_id": document.source_id,
                "product_key": product_key,
                "product": arbitration.display_name,
                "reason": f"{fallback_reason}:llm_unavailable",
                "evidence": _review_evidence(llm_candidates, kind="candidate_context"),
            })
            continue
        if not llm_candidates:
            if rule_candidate is not None:
                analyses.append(rule_candidate)
            review_queue.append({
                "source_id": document.source_id,
                "product_key": product_key,
                "product": arbitration.display_name,
                "reason": f"{fallback_reason}:no_product_scoped_context",
                "evidence": _review_evidence((), kind="candidate_context"),
            })
            continue
        llm_count += 1
        diagnostic: dict[str, Any] | None = None
        parse_error_rows: list[dict[str, str]] = []
        total_attempt_count = 0
        total_transport_retries = 0
        correction_retry_count = 0
        total_llm_duration_ms = 0
        try:
            messages = build_llm_context(
                title=document.title,
                product=arbitration.display_name,
                arbitration=arbitration,
                config=config,
                evidence_candidates=list(llm_candidates),
            )
            initial_call = _as_call_result(llm_client.complete(messages), config=config)
            total_attempt_count += initial_call.attempt_count
            total_transport_retries += initial_call.transport_retry_count
            total_llm_duration_ms += initial_call.duration_ms
            raw = initial_call.content
            allowed_evidence_ids = frozenset(item.evidence_id for item in llm_candidates)
            outputs, parse_errors = parse_llm_response(
                raw,
                expected_product_key=product_key,
                expected_evidence_ids=allowed_evidence_ids,
            )
            parse_error_rows.extend(item.to_dict(phase="initial") for item in parse_errors)

            final_call = initial_call
            final_parse_errors = parse_errors
            if not outputs and parse_errors:
                correction_retry_count = 1
                correction_messages = build_llm_correction_context(
                    messages,
                    raw_response=raw,
                    expected_product_key=product_key,
                    product=arbitration.display_name,
                    parse_errors=parse_errors,
                    allowed_evidence_ids=tuple(item.evidence_id for item in llm_candidates),
                )
                try:
                    correction_call = _as_call_result(llm_client.complete(correction_messages), config=config)
                    final_call = correction_call
                    total_attempt_count += correction_call.attempt_count
                    total_transport_retries += correction_call.transport_retry_count
                    total_llm_duration_ms += correction_call.duration_ms
                    raw = correction_call.content
                    outputs, final_parse_errors = parse_llm_response(
                        raw,
                        expected_product_key=product_key,
                        expected_evidence_ids=allowed_evidence_ids,
                    )
                    parse_error_rows.extend(item.to_dict(phase="correction") for item in final_parse_errors)
                    if outputs:
                        llm_recovered_count += 1
                except LLMRequestError as exc:
                    total_attempt_count += exc.attempt_count
                    total_transport_retries += exc.transport_retry_count
                    diagnostic = exc.to_diagnostic()
                    diagnostic.update(
                        {
                            "parse_errors": parse_error_rows,
                            "attempt_count": total_attempt_count,
                            "transport_retry_count": total_transport_retries,
                            "correction_retry_count": correction_retry_count,
                            "retry_exhausted": True,
                        }
                    )

            if outputs:
                output = outputs[0]
                selected_candidates = _selected_candidates(
                    llm_candidates,
                    output.evidence_ids,
                )
                selected_excerpts = tuple(_candidate_excerpt(item) for item in selected_candidates)
                llm_needs_review = output.confidence < 0.50 or not selected_excerpts
                analyses.append(
                    AnalysisResult(
                        source_id=document.source_id,
                        product_key=output.product_key,
                        product=output.product,
                        direction=output.direction,
                        reason=output.reason,
                        confidence=output.confidence,
                        method="llm",
                        need_manual_review=llm_needs_review,
                        evidence=tuple(item.quote for item in selected_candidates),
                        evidence_excerpts=selected_excerpts,
                        processing_stats={
                            "rule_margin": arbitration.margin,
                            "llm_errors": parse_error_rows,
                            "fallback_reason": fallback_reason,
                            "model_name": final_call.model or config.llm_model,
                            "llm_duration_ms": total_llm_duration_ms,
                            "llm_retry_count": total_transport_retries + correction_retry_count,
                            "transport_retry_count": total_transport_retries,
                            "correction_retry_count": correction_retry_count,
                        },
                    )
                )
                if llm_needs_review:
                    review_queue.append({
                        "source_id": document.source_id,
                        "product_key": product_key,
                        "product": output.product,
                        "reason": "llm_evidence_quality_failed",
                        "evidence": _review_evidence(
                            selected_candidates or llm_candidates,
                            kind="verified" if selected_candidates else "candidate_context",
                        ),
                    })
                llm_retry_count += total_transport_retries + correction_retry_count
                continue
            if diagnostic is None:
                diagnostic = _parse_failure_diagnostic(
                    final_parse_errors,
                    parse_error_rows=parse_error_rows,
                    raw_response=raw,
                    call=final_call,
                    attempt_count=total_attempt_count,
                    transport_retry_count=total_transport_retries,
                    correction_retry_count=correction_retry_count,
                    secrets=(config.llm_api_key,),
                )
            llm_retry_count += total_transport_retries + correction_retry_count
        except LLMRequestError as exc:
            diagnostic = exc.to_diagnostic()
            llm_retry_count += exc.transport_retry_count
        except Exception as exc:
            diagnostic = {
                "error_type": "unexpected_error",
                "message": sanitize_text(exc, secrets=(config.llm_api_key,), limit=1000),
                "parse_errors": parse_error_rows,
                "raw_response_excerpt": "",
                "provider": config.llm_provider,
                "attempt_count": total_attempt_count,
                "transport_retry_count": total_transport_retries,
                "correction_retry_count": correction_retry_count,
                "retry_exhausted": False,
            }
            llm_retry_count += total_transport_retries + correction_retry_count
        diagnostic = diagnostic or {
            "error_type": "unexpected_error",
            "message": "大模型未返回可用结果",
            "parse_errors": parse_error_rows,
            "raw_response_excerpt": "",
            "provider": config.llm_provider,
            "attempt_count": total_attempt_count,
            "transport_retry_count": total_transport_retries,
            "correction_retry_count": correction_retry_count,
            "retry_exhausted": False,
        }
        llm_error_types[str(diagnostic["error_type"])] += 1
        errors.append({"product_key": product_key, "diagnostic": diagnostic})
        if rule_candidate is not None:
            analyses.append(rule_candidate)
        review_queue.append({
            "source_id": document.source_id,
            "product_key": product_key,
            "product": arbitration.display_name,
            "reason": "llm_error_or_invalid_output",
            "evidence": _review_evidence(
                llm_candidates,
                kind="candidate_context",
                diagnostic=diagnostic,
            ),
        })
    # A product match without any direction signal is still an actionable
    # review item.  Do not silently lose navigation-page matches, OCR noise,
    # or articles that mention a product but express no view.
    matched_product_keys = {match.product_key for match in matches}
    for product_key in sorted(matched_product_keys - set(grouped)):
        product_matches = tuple(match for match in matches if match.product_key == product_key)
        match = product_matches[0]
        related_only = is_related_mention_only(product_key, product_matches, sections)
        if related_only:
            evidence: Any = {
                "excerpts": [
                    {"quote": quote} for quote in _related_mention_quotes(document.raw_text, product_matches, sections)
                ]
            }
            reason = "related_product_mention_only"
        else:
            evidence = _quality_evidence(
                document,
                product_key=product_key,
                direction=None,
                signals=signals,
                matches=matches,
                allow_cross_product=True,
            )
            reason = "no_signal"
        review_queue.append(
            {
                "source_id": document.source_id,
                "product_key": product_key,
                "product": match.display_name,
                "reason": reason,
                "evidence": evidence,
            }
        )
    if not matches:
        review_queue.append({"source_id": document.source_id, "reason": "no_product_match"})
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    stats = {
        "match_count": len(matches),
        "signal_count": len(signals),
        "rule_count": rule_count,
        "llm_count": llm_count,
        "llm_retry_count": llm_retry_count,
        "llm_recovered_count": llm_recovered_count,
        "llm_error_by_type": dict(sorted(llm_error_types.items())),
        "review_count": len(review_queue),
        "duration_ms": elapsed_ms,
        "pipeline_version": config.pipeline_version,
    }
    return DocumentProcessingResult(document, matches, signals, tuple(analyses), tuple(review_queue), tuple(errors), stats)


def _as_call_result(value: LLMCallResult | str, *, config: ProcessingConfig) -> LLMCallResult:
    if isinstance(value, LLMCallResult):
        return value
    return LLMCallResult(content=str(value), provider=config.llm_provider, model=config.llm_model)


def _parse_failure_diagnostic(
    parse_errors: list[LLMParseError],
    *,
    parse_error_rows: list[dict[str, str]],
    raw_response: str,
    call: LLMCallResult,
    attempt_count: int,
    transport_retry_count: int,
    correction_retry_count: int,
    secrets: tuple[str, ...],
) -> dict[str, Any]:
    primary = parse_errors[0] if parse_errors else LLMParseError(
        "provider_response_error", "大模型未返回可用结果"
    )
    diagnostic: dict[str, Any] = {
        "error_type": primary.error_type,
        "message": primary.message,
        "parse_errors": parse_error_rows,
        "raw_response_excerpt": sanitize_text(raw_response, secrets=secrets, limit=500),
        "provider": call.provider,
        "attempt_count": attempt_count,
        "transport_retry_count": transport_retry_count,
        "correction_retry_count": correction_retry_count,
        "retry_exhausted": bool(correction_retry_count),
    }
    if call.http_status is not None:
        diagnostic["http_status"] = call.http_status
    if call.content_type:
        diagnostic["content_type"] = call.content_type
    if call.sse_line_count is not None:
        diagnostic["sse_line_count"] = call.sse_line_count
    if call.sse_event_samples:
        diagnostic["sse_event_samples"] = list(call.sse_event_samples)
    if call.done_received is not None:
        diagnostic["done_received"] = call.done_received
    return diagnostic


def _rule_result(
    document: Document,
    arbitration: Any,
    *,
    evidence: tuple[str, ...] | None = None,
    need_manual_review: bool = False,
) -> AnalysisResult:
    resolved_evidence = evidence if evidence is not None else arbitration.evidence_snippets
    reason = _short_reason(resolved_evidence)
    return AnalysisResult(
        source_id=document.source_id,
        product_key=arbitration.product_key,
        product=arbitration.display_name,
        direction=arbitration.direction,
        reason=reason,
        confidence=arbitration.confidence,
        method="rule",
        need_manual_review=need_manual_review or arbitration.confidence < 0.50,
        evidence=resolved_evidence,
        processing_stats={
            "bullish_score": arbitration.bullish_score,
            "bearish_score": arbitration.bearish_score,
            "neutral_score": arbitration.neutral_score,
            "margin": arbitration.margin,
            "signal_count": len(arbitration.signals),
        },
    )


def _quality_evidence(
    document: Document,
    *,
    product_key: str,
    direction: str | None,
    signals: tuple[DirectionSignal, ...],
    matches: tuple[LexiconMatch, ...],
    allow_cross_product: bool = False,
) -> dict[str, Any]:
    cleaned_text = document.cleaned_text or str(document.metadata.get("cleaned_text") or document.raw_text)
    return build_product_evidence(
        product_key=product_key,
        direction=direction,
        cleaned_text=cleaned_text,
        raw_text=document.raw_text,
        signals=list(signals),
        matches=list(matches),
        allow_cross_product=allow_cross_product,
    )


def _evidence_quotes(evidence: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(excerpt.get("quote") or "")
        for excerpt in evidence.get("excerpts", [])
        if str(excerpt.get("quote") or "").strip()
    )


def _selected_candidates(
    candidates: tuple[EvidenceCandidate, ...],
    evidence_ids: tuple[str, ...],
) -> tuple[EvidenceCandidate, ...]:
    by_id = {item.evidence_id: item for item in candidates}
    return tuple(by_id[item] for item in evidence_ids if item in by_id)


def _candidate_excerpt(candidate: EvidenceCandidate) -> EvidenceExcerpt:
    return EvidenceExcerpt(
        quote=candidate.quote,
        raw_quote=candidate.raw_quote,
        source=candidate.source,
        start_char=candidate.start_char,
        end_char=candidate.end_char,
        match_type="llm_selected",
        validated=True,
    )


def _review_evidence(
    candidates: tuple[EvidenceCandidate, ...] | list[EvidenceCandidate],
    *,
    kind: str,
    diagnostic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verified = kind == "verified"
    evidence: dict[str, Any] = {
        "kind": kind,
        "notes": (
            "证据编号已由大模型选择并通过原文位置校验。"
            if verified
            else "以下内容仅是待人工核对的原文上下文，不代表已经支持模型结论。"
        ),
        "excerpts": [
            {
                "quote": item.quote,
                "raw_quote": item.raw_quote,
                "source": item.source,
                "start_char": item.start_char,
                "end_char": item.end_char,
                "match_type": "llm_selected" if verified else "context",
                "validated": verified,
            }
            for item in candidates
        ],
    }
    if diagnostic is not None:
        evidence["diagnostic"] = diagnostic
    return evidence


def _short_reason(snippets: tuple[str, ...]) -> str:
    """Keep UI-facing reasons short; full text stays in structured evidence."""
    import re

    unique: list[str] = []
    seen: set[str] = set()
    for item in snippets:
        compact = re.sub(r"\s+", " ", item).strip()
        if compact and compact not in seen:
            seen.add(compact)
            unique.append(compact)
    text = "；".join(unique[:3])
    return text


def _related_mention_quotes(
    text: str,
    product_matches: tuple[LexiconMatch, ...],
    sections: tuple[ProductSection, ...],
) -> tuple[str, ...]:
    quotes: list[str] = []
    for match in product_matches:
        section = section_for_position(sections, match.start)
        if section is None:
            continue
        previous = max(text.rfind(mark, section.body_start, match.start) for mark in "。！？!?")
        start = section.body_start if previous < 0 else previous + 1
        endings = [text.find(mark, match.end, section.body_end) for mark in "。！？!?"]
        endings = [position for position in endings if position >= 0]
        end = min(endings) + 1 if endings else min(section.body_end, match.end + 240)
        quote = re.sub(r"\s+", " ", text[start:end]).strip()
        quote = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", quote)
        if quote and quote not in quotes:
            quotes.append(quote[:600])
        if len(quotes) >= 3:
            break
    return tuple(quotes)
