"""Canonical result contract for the backend integration boundary."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any, TYPE_CHECKING

from data_proccessing.llm.diagnostics import LLM_ERROR_TYPES
from data_proccessing.models import (
    AnalysisResult,
    DirectionSignal,
    EvidenceCandidate,
    EvidenceExcerpt,
)
from data_proccessing.instrument_mapping.runtime import LexiconMatch
from data_proccessing.sections import HEADING_PATTERN, build_product_sections, product_section_spans

if TYPE_CHECKING:
    from data_proccessing.pipeline.processor import DocumentProcessingResult


CANONICAL_VERSION = "dp-0.1.0"
_DIRECTIONS = {"看涨", "看跌", "中性"}
_METHODS = {"rule", "llm", "manual"}


def to_canonical_result(
    result: DocumentProcessingResult,
    *,
    pipeline_version: str = CANONICAL_VERSION,
) -> dict[str, Any]:
    """Convert internal dataclasses into the one object consumed by the API.

    JSONL debug files remain an implementation detail.  This object is stable,
    deterministic, and contains structured, product-scoped evidence.
    """
    document = result.document
    cleaned_text = document.cleaned_text or str(document.metadata.get("cleaned_text") or document.raw_text)
    results = [
        _result_to_dict(
            item,
            cleaned_text=cleaned_text,
            raw_text=document.raw_text,
            signals=list(result.signals),
            matches=list(result.matches),
        )
        for item in result.analyses
        if item.product_key and item.direction in _DIRECTIONS and item.method in _METHODS
    ]
    stats = dict(result.processing_stats)
    stats.update(
        {
            "matched_products": len({item.product_key for item in result.matches}),
            "signal_count": len(result.signals),
            "rule_results": sum(item.method == "rule" for item in result.analyses),
            "llm_results": sum(item.method == "llm" for item in result.analyses),
            "error_count": len(result.errors),
        }
    )
    return {
        "source_id": document.source_id,
        "pipeline_version": pipeline_version,
        "document": {
            "title": document.title or document.file_name or document.source_id,
            "source": document.source or str(document.metadata.get("source") or ""),
            "company": document.company or str(document.metadata.get("company") or ""),
            "file_type": _file_type(document.file_type),
            "publish_time": document.publish_time or document.metadata.get("publish_time"),
            "raw_text": document.raw_text,
            "cleaned_text": cleaned_text,
        },
        "results": results,
        "review_queue": [_review_item(item) for item in result.review_queue],
        "processing_stats": stats,
    }


def validate_canonical_result(payload: dict[str, Any]) -> None:
    """Validate the fields that are unsafe to coerce at the DB boundary."""
    if not isinstance(payload, dict) or not str(payload.get("source_id") or "").strip():
        raise ValueError("source_id is required")
    document = payload.get("document")
    if not isinstance(document, dict) or not str(document.get("title") or "").strip():
        raise ValueError("document.title is required")
    for index, item in enumerate(payload.get("results") or []):
        if not isinstance(item, dict):
            raise ValueError(f"results[{index}] must be an object")
        if not str(item.get("product_key") or "").strip():
            raise ValueError(f"results[{index}].product_key is required")
        if item.get("direction") not in _DIRECTIONS:
            raise ValueError(f"results[{index}].direction is invalid")
        if item.get("analysis_method") not in _METHODS:
            raise ValueError(f"results[{index}].analysis_method is invalid")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ValueError(f"results[{index}].confidence is invalid")
    for index, item in enumerate(payload.get("review_queue") or []):
        if not isinstance(item, dict):
            raise ValueError(f"review_queue[{index}] must be an object")
        evidence = item.get("evidence")
        diagnostic = evidence.get("diagnostic") if isinstance(evidence, dict) else None
        if diagnostic is None:
            continue
        if not isinstance(diagnostic, dict):
            raise ValueError(f"review_queue[{index}].evidence.diagnostic must be an object")
        if diagnostic.get("error_type") not in LLM_ERROR_TYPES:
            raise ValueError(f"review_queue[{index}].evidence.diagnostic.error_type is invalid")


def _result_to_dict(
    item: AnalysisResult,
    *,
    cleaned_text: str,
    raw_text: str,
    signals: list[DirectionSignal],
    matches: list[LexiconMatch],
) -> dict[str, Any]:
    if item.method == "llm":
        evidence = build_validated_llm_evidence(
            product_key=item.product_key,
            raw_text=raw_text,
            matches=matches,
            excerpts=list(item.evidence_excerpts),
        )
        reason = item.reason
    else:
        evidence = build_product_evidence(
            product_key=item.product_key,
            direction=item.direction,
            cleaned_text=cleaned_text,
            raw_text=raw_text,
            signals=signals,
            matches=matches,
        )
        reason = evidence["summary"]
    return {
        "product_key": item.product_key,
        "product": item.product,
        "contract": item.contract,
        "contract_key": item.contract_key,
        "direction": item.direction,
        "reason": reason,
        "confidence": round(float(item.confidence), 4),
        "analysis_method": item.method,
        "need_manual_review": bool(item.need_manual_review or not evidence["excerpts"]),
        "evidence": evidence,
        "metadata": dict(item.processing_stats),
        "model_name": item.processing_stats.get("model_name"),
        "llm_duration_ms": item.processing_stats.get("llm_duration_ms"),
        "llm_retry_count": item.processing_stats.get("llm_retry_count"),
        "llm_error_msg": item.processing_stats.get("llm_error_msg"),
    }


def build_product_evidence(
    *,
    product_key: str,
    direction: str | None,
    cleaned_text: str,
    raw_text: str,
    signals: list[DirectionSignal],
    matches: list[LexiconMatch],
    allow_cross_product: bool = False,
) -> dict[str, Any]:
    # Signal offsets are produced from raw_text.  Only claim cleaned_text
    # offsets when both strings are identical; otherwise retain raw positions.
    source_name = "cleaned_text" if cleaned_text and cleaned_text == raw_text else "raw_text"
    source_text = cleaned_text if source_name == "cleaned_text" else raw_text
    product_matches = [match for match in matches if match.product_key == product_key]
    other_matches = [match for match in matches if match.product_key != product_key]
    sections = _product_sections(source_text, product_key, product_matches, matches)
    scoped_signals = [
        signal
        for signal in signals
        if signal.product_key == product_key
        and (direction is None or signal.direction == direction)
        and any(start <= signal.start < signal.end <= end for start, end in sections)
    ]

    excerpts: list[dict[str, Any]] = []
    for signal in sorted(scoped_signals, key=lambda value: (value.start, value.end)):
        section = next(
            ((start, end) for start, end in sections if start <= signal.start < signal.end <= end),
            None,
        )
        if section is None:
            continue
        span = _complete_sentence_span(source_text, signal.start, signal.end, *section)
        if span is None:
            continue
        start, end = span
        raw_quote = source_text[start:end]
        quote = _clean_evidence_quote(raw_quote)
        if not _is_valid_complete_quote(quote):
            continue
        if not allow_cross_product and _contains_unexplained_other_product(
            source_text,
            start,
            end,
            quote,
            product_key,
            signal.start,
            signal.end,
            product_matches,
            other_matches,
        ):
            continue
        candidate = {
            "quote": quote,
            "raw_quote": raw_quote,
            "source": source_name,
            "start_char": start,
            "end_char": end,
            "match_type": "reason",
        }
        if not _overlaps_existing_excerpt(candidate, excerpts):
            excerpts.append(candidate)
        if len(excerpts) >= 3:
            break

    # LLM fallback may inspect the complete product section even when no
    # sentence passes the final evidence gate.  These context excerpts are
    # never accepted as formal evidence unless a later strict pass succeeds.
    if not excerpts and allow_cross_product:
        for start, end in sections[:3]:
            raw_quote = source_text[start:end]
            quote = _clean_evidence_quote(raw_quote)
            if quote:
                excerpts.append(
                    {
                        "quote": quote,
                        "raw_quote": raw_quote,
                        "source": source_name,
                        "start_char": start,
                        "end_char": end,
                        "match_type": "fallback",
                    }
                )

    reason = " ".join(str(excerpt["quote"]) for excerpt in excerpts)
    return {
        "summary": reason,
        "source": source_name if excerpts else "analysis_reason",
        "section_type": "core",
        "kind": "verified" if excerpts else "candidate_context",
        "excerpts": excerpts,
        "notes": (
            "证据来自当前 product_key 对应章节中的完整句子。"
            if excerpts
            else "未能在当前 product_key 章节内定位完整证据，需人工复核。"
        ),
    }


def build_evidence_candidates(
    *,
    product_key: str,
    raw_text: str,
    matches: list[LexiconMatch] | tuple[LexiconMatch, ...],
    max_candidates: int = 6,
    max_chars: int = 1200,
) -> tuple[EvidenceCandidate, ...]:
    """Build deterministic, source-addressable sentences for one product."""
    all_matches = tuple(matches)
    product_matches = tuple(match for match in all_matches if match.product_key == product_key)
    spans = product_section_spans(
        raw_text,
        product_key=product_key,
        product_matches=product_matches,
        all_matches=all_matches,
    )
    sections = build_product_sections(raw_text, all_matches)
    rows: list[tuple[int, int, str, str, bool, int]] = []
    for section_start, section_end in spans:
        section = next(
            (
                item for item in sections
                if item.body_start == section_start and item.body_end == section_end
            ),
            None,
        )
        shared = bool(section and len(section.concrete_product_keys) > 1)
        for start, end in _sentence_spans(raw_text, section_start, section_end):
            raw_quote = raw_text[start:end]
            quote = _clean_evidence_quote(raw_quote)
            if not _is_candidate_quote(quote):
                continue
            target_in_sentence = any(start <= match.start < end for match in product_matches)
            other_keys = {
                match.product_key
                for match in all_matches
                if match.product_key != product_key and start <= match.start < end
            }
            # A sentence explicitly anchored only to another product is context
            # for that product, not for the heading owner (e.g. 玉米淀粉 vs 玉米).
            if other_keys and not target_in_sentence:
                continue
            if shared and not target_in_sentence:
                continue
            conclusion_score = sum(marker in quote for marker in _CONCLUSION_MARKERS)
            rows.append((start, end, raw_quote, quote, target_in_sentence, conclusion_score))

    ordered_source = sorted(rows, key=lambda item: (item[0], item[1]))
    indexed = [
        (f"E{index}", row)
        for index, row in enumerate(ordered_source, start=1)
    ]
    ranked = sorted(
        indexed,
        key=lambda item: (
            -item[1][5],
            -int(item[1][4]),
            item[1][0],
        ),
    )
    selected: list[EvidenceCandidate] = []
    used_chars = 0
    for evidence_id, (start, end, raw_quote, quote, _target, _score) in ranked:
        if len(quote) > max_chars or used_chars + len(quote) > max_chars:
            continue
        selected.append(
            EvidenceCandidate(
                evidence_id=evidence_id,
                product_key=product_key,
                quote=quote,
                raw_quote=raw_quote,
                source="raw_text",
                start_char=start,
                end_char=end,
            )
        )
        used_chars += len(quote)
        if len(selected) >= max_candidates:
            break
    return tuple(selected)


def build_validated_llm_evidence(
    *,
    product_key: str,
    raw_text: str,
    matches: list[LexiconMatch] | tuple[LexiconMatch, ...],
    excerpts: list[EvidenceExcerpt] | tuple[EvidenceExcerpt, ...],
) -> dict[str, Any]:
    product_matches = [match for match in matches if match.product_key == product_key]
    sections = product_section_spans(
        raw_text,
        product_key=product_key,
        product_matches=product_matches,
        all_matches=matches,
    )
    valid: list[dict[str, Any]] = []
    for excerpt in excerpts:
        start = int(excerpt.start_char)
        end = int(excerpt.end_char)
        if not any(section_start <= start < end <= section_end for section_start, section_end in sections):
            continue
        if raw_text[start:end] != excerpt.raw_quote:
            continue
        valid.append(
            {
                "quote": excerpt.quote,
                "raw_quote": excerpt.raw_quote,
                "source": excerpt.source,
                "start_char": start,
                "end_char": end,
                "match_type": excerpt.match_type,
                "validated": True,
            }
        )
    return {
        "summary": " ".join(str(item["quote"]) for item in valid),
        "source": "raw_text" if valid else "analysis_reason",
        "section_type": "core",
        "kind": "verified" if valid else "candidate_context",
        "excerpts": valid,
        "notes": (
            "证据由大模型选择的编号还原，并通过原文位置校验。"
            if valid
            else "大模型未返回可精确回指当前品种章节的证据，需人工复核。"
        ),
    }


_HEADING_PATTERN = HEADING_PATTERN
_SENTENCE_ENDINGS = "。！？!?"
_COMPARISON_MARKERS = (
    "跟随",
    "价差",
    "联动",
    "替代",
    "相比",
    "相较",
    "带动",
    "成本",
    "矛盾",
    "关注",
    "提振",
)
_CONCLUSION_MARKERS = (
    "综合来看",
    "总体来看",
    "预计",
    "预期",
    "短期",
    "后期",
    "操作方面",
    "建议",
    "维持",
)
_BOILERPLATE_MARKERS = (
    "重要声明",
    "免责声明",
    "本报告由",
    "不构成对客户的投资建议",
    "东海期货力求报告内容",
    "报告中的观点、结论和建议",
    "信息和建议不会发生任何变更",
    "在任何情况下，本公司不对",
    "交易者需自行承担风险",
    "本报告版权",
    "未经书面许可",
    "版权所有",
    "联系人",
    "网址",
    "数据来自",
)


def _product_sections(
    text: str,
    product_key: str,
    product_matches: list[LexiconMatch],
    all_matches: list[LexiconMatch],
) -> list[tuple[int, int]]:
    return product_section_spans(
        text,
        product_key=product_key,
        product_matches=product_matches,
        all_matches=all_matches,
    )


def _complete_sentence_span(
    text: str,
    signal_start: int,
    signal_end: int,
    section_start: int,
    section_end: int,
) -> tuple[int, int] | None:
    previous = max(text.rfind(mark, section_start, signal_start) for mark in _SENTENCE_ENDINGS)
    start = section_start if previous < 0 else previous + 1
    endings = [text.find(mark, signal_end, section_end) for mark in _SENTENCE_ENDINGS]
    endings = [position for position in endings if position >= 0]
    if not endings:
        return None
    end = min(endings) + 1
    while start < end and text[start].isspace():
        start += 1
    return (start, end) if start < signal_start < end else None


def _clean_evidence_quote(value: str) -> str:
    text = re.sub(r"\[PAGE\s+\d+\]", " ", value, flags=re.IGNORECASE)
    text = re.sub(r"HTTP://WWW\.QH168\.COM\.CN", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s*/\s*\d+\b", " ", text)
    text = text.replace("请务必仔细阅读正文后免责申明", " ")
    text = text.replace("研究所晨会观点精粹", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。；：！？!?%])", r"\1", text)
    return text.strip()


def _is_valid_complete_quote(quote: str) -> bool:
    if len(quote) < 8 or quote[-1] not in _SENTENCE_ENDINGS:
        return False
    if quote[0] in "，。；：！？!?%、,." or re.match(r"^\.\d", quote):
        return False
    if _HEADING_PATTERN.search(quote):
        return False
    return True


def _contains_unexplained_other_product(
    text: str,
    start: int,
    end: int,
    quote: str,
    product_key: str,
    signal_start: int,
    signal_end: int,
    product_matches: list[LexiconMatch],
    other_matches: list[LexiconMatch],
) -> bool:
    has_other = any(
        match.product_key != product_key and start <= match.start < end
        for match in other_matches
    )
    if not has_other:
        return False
    clause_start, clause_end = _clause_span(text, signal_start, signal_end, start, end)
    target_in_clause = any(clause_start <= match.start < clause_end for match in product_matches)
    other_in_clause = any(clause_start <= match.start < clause_end for match in other_matches)
    if target_in_clause and not other_in_clause:
        return False
    return not any(marker in quote for marker in _COMPARISON_MARKERS)


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    for found in re.finditer(r"[。！？!?]", text[start:end]):
        sentence_end = start + found.end()
        sentence_start = cursor
        while sentence_start < sentence_end and text[sentence_start].isspace():
            sentence_start += 1
        if sentence_start < sentence_end:
            spans.append((sentence_start, sentence_end))
        cursor = sentence_end
    return spans


def _is_candidate_quote(quote: str) -> bool:
    if len(quote) < 6 or len(quote) > 600 or quote[-1] not in _SENTENCE_ENDINGS:
        return False
    if quote[0] in "，。；：！？!?%、,." or _HEADING_PATTERN.search(quote):
        return False
    return not any(marker in quote for marker in _BOILERPLATE_MARKERS)


def _clause_span(
    text: str,
    signal_start: int,
    signal_end: int,
    sentence_start: int,
    sentence_end: int,
) -> tuple[int, int]:
    delimiters = "，,；;。！？!?\n"
    previous = max(text.rfind(mark, sentence_start, signal_start) for mark in delimiters)
    start = sentence_start if previous < 0 else previous + 1
    endings = [text.find(mark, signal_end, sentence_end) for mark in delimiters]
    endings = [position for position in endings if position >= 0]
    end = min(endings) + 1 if endings else sentence_end
    return start, end


def _overlaps_existing_excerpt(candidate: dict[str, Any], excerpts: list[dict[str, Any]]) -> bool:
    start = int(candidate["start_char"])
    end = int(candidate["end_char"])
    quote = str(candidate["quote"])
    for existing in excerpts:
        other_start = int(existing["start_char"])
        other_end = int(existing["end_char"])
        other_quote = str(existing["quote"])
        overlap = max(0, min(end, other_end) - max(start, other_start))
        shorter = max(1, min(end - start, other_end - other_start))
        if quote == other_quote or quote in other_quote or other_quote in quote or overlap / shorter >= 0.8:
            return True
    return False


def _review_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    return asdict(item) if hasattr(item, "__dataclass_fields__") else {"reason": str(item)}


def _short_reason(reason: str) -> str:
    text = _compact(reason)
    if not text:
        return ""
    sentences = re.split(r"(?<=[。！？!?；;])", text)
    unique: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        sentence = sentence.strip()
        if sentence and sentence not in seen:
            seen.add(sentence)
            unique.append(sentence)
    return "".join(unique[:3])


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _file_type(value: str) -> str:
    value = (value or "txt").lower().lstrip(".")
    return "image" if value in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"} else value
