import re

from back_end.app.api.schemas import datetime_to_iso
from back_end.app.core.display import is_displayable_analysis_result
from back_end.app.core.review import clean_review_evidence, trigger_reason_label
from back_end.app.models import AnalysisResult, Article, ArticleProductSegment, ArticleText, ManualConfirmation, TaskLog
from pn05.display_cleaner import clean_display_text
from data_proccessing.catalog import PRODUCT_CATALOG, ProductDefinition, get_product, product_group, product_key_for_name


def get_displayable_analysis_results(article: Article) -> list[AnalysisResult]:
    return sorted(
        [
            result
            for result in article.analysis_results
            if is_displayable_analysis_result(result)
        ],
        key=lambda item: (not item.is_primary, item.product, item.contract_key, item.id),
    )


def get_displayable_primary_analysis_result(article: Article) -> AnalysisResult | None:
    results = get_displayable_analysis_results(article)
    if not results:
        return None
    primary = [result for result in results if result.is_primary]
    if primary:
        return sorted(primary, key=lambda item: item.id or 0)[0]
    return sorted(
        results,
        key=lambda item: (item.confidence or 0.0, -(item.id or 0)),
        reverse=True,
    )[0]


def serialize_analysis_result(
    result: AnalysisResult | None,
    *,
    article_text: ArticleText | None = None,
    product_segments: list[ArticleProductSegment] | None = None,
) -> dict | None:
    if result is None:
        return None
    return {
        "id": result.id,
        "article_id": result.article_id,
        "product": result.product,
        "product_key": result.product_key,
        "product_group": product_group(result.product_key),
        "contract": result.contract,
        "contract_key": result.contract_key,
        "direction": result.direction,
        "reason": clean_display_text(result.reason),
        "confidence": result.confidence,
        "analysis_method": result.analysis_method,
        "need_manual_review": result.need_manual_review,
        "is_primary": result.is_primary,
        "model_name": result.model_name,
        "llm_duration_ms": result.llm_duration_ms,
        "llm_retry_count": result.llm_retry_count,
        "llm_error_msg": result.llm_error_msg,
        "analysis_time": datetime_to_iso(result.analysis_time),
        "evidence": result.evidence_json or build_segment_evidence(result, product_segments) or build_analysis_evidence(result, article_text),
    }


def serialize_article_list_item(article: Article) -> dict:
    result = get_displayable_primary_analysis_result(article)
    return {
        "id": article.id,
        "title": article.title,
        "source": article.source,
        "company": article.company,
        "file_url": article.file_url,
        "file_type": article.file_type,
        "publish_time": datetime_to_iso(article.publish_time),
        "status": article.status,
        "error_msg": article.error_msg,
        "created_at": datetime_to_iso(article.created_at),
        "updated_at": datetime_to_iso(article.updated_at),
        "product": result.product if result else None,
        "product_key": result.product_key if result else None,
        "product_group": product_group(result.product_key) if result else None,
        "direction": result.direction if result else None,
        "reason": clean_display_text(result.reason) if result else None,
        "confidence": result.confidence if result else None,
        "need_manual_review": result.need_manual_review if result else False,
        "analysis_time": datetime_to_iso(result.analysis_time) if result else None,
    }


def serialize_article_text(article_text: ArticleText | None) -> dict | None:
    if article_text is None:
        return None
    return {
        "id": article_text.id,
        "article_id": article_text.article_id,
        "raw_text": article_text.raw_text,
        "cleaned_text": article_text.cleaned_text,
        "refined_text": article_text.refined_text,
        "raw_length": article_text.raw_length,
        "cleaned_length": article_text.cleaned_length,
        "refined_length": article_text.refined_length,
        "parser_type": article_text.parser_type,
        "created_at": datetime_to_iso(article_text.created_at),
        "updated_at": datetime_to_iso(article_text.updated_at),
    }


def serialize_task_log(log: TaskLog) -> dict:
    return {
        "id": log.id,
        "article_id": log.article_id,
        "stage": log.stage,
        "status": log.status,
        "message": log.message,
        "duration_ms": log.duration_ms,
        "created_at": datetime_to_iso(log.created_at),
    }


def serialize_manual_confirmation(confirmation: ManualConfirmation) -> dict:
    return {
        "id": confirmation.id,
        "article_id": confirmation.article_id,
        "original_product": confirmation.original_product,
        "original_product_key": confirmation.original_product_key,
        "original_direction": confirmation.original_direction,
        "original_reason": confirmation.original_reason,
        "original_confidence": confirmation.original_confidence,
        "confirmed_product": confirmation.confirmed_product,
        "confirmed_product_key": confirmation.confirmed_product_key,
        "confirmed_direction": confirmation.confirmed_direction,
        "confirmed_reason": confirmation.confirmed_reason,
        "confirmed_confidence": confirmation.confirmed_confidence,
        "confirmed_by": confirmation.confirmed_by,
        "note": confirmation.note,
        "confirmed_at": datetime_to_iso(confirmation.confirmed_at),
    }


def serialize_article_detail(article: Article) -> dict:
    analysis_results = get_displayable_analysis_results(article)
    analysis_result = get_displayable_primary_analysis_result(article)
    return {
        "article": serialize_article_list_item(article),
        "text": serialize_article_text(article.text),
        "analysis_result": serialize_analysis_result(
            analysis_result,
            article_text=article.text,
            product_segments=article.product_segments,
        ),
        "analysis_results": [
            serialize_analysis_result(
                result,
                article_text=article.text,
                product_segments=article.product_segments,
            )
            for result in analysis_results
        ],
        "task_logs": [
            serialize_task_log(log)
            for log in sorted(article.task_logs, key=lambda item: item.id)
        ],
        "manual_confirmations": [
            serialize_manual_confirmation(confirmation)
            for confirmation in sorted(article.manual_confirmations, key=lambda item: item.id)
        ],
        "review_queue": [
            {
                "id": item.id,
                "product_key": item.product_key,
                "product": item.product,
                "reason": item.reason,
                "reason_label": trigger_reason_label(item.reason),
                "evidence": clean_review_evidence(item.evidence_json),
                "status": item.status,
                "reviewed_by": item.reviewed_by,
                "review_reason_code": item.review_reason_code,
                "review_note": item.review_note,
                "reviewed_at": datetime_to_iso(item.reviewed_at),
                "created_at": datetime_to_iso(item.created_at),
            }
            for item in sorted(article.review_queue, key=lambda item: item.id)
        ],
    }


def build_segment_evidence(
    result: AnalysisResult,
    product_segments: list[ArticleProductSegment] | None,
) -> dict | None:
    """Build evidence directly from persisted product segments when available."""
    segment = _best_segment_for_result(result, product_segments or [])
    if segment is None:
        return None

    cleaned_text = _clean_evidence_display_text(segment.cleaned_text)
    refined_text = _clean_evidence_display_text(segment.refined_text)
    quote_source = refined_text or cleaned_text
    quote = _compact_text(quote_source[:360])
    return {
        "summary": _clean_evidence_display_text(result.reason),
        "source": "segment",
        "section_type": segment.section_type,
        "cleaned_text": cleaned_text,
        "refined_text": refined_text,
        "excerpts": [
            {
                "quote": quote,
                "source": "segment",
                "start_char": segment.start_char,
                "end_char": segment.end_char,
                "match_type": "fallback",
            }
        ] if quote else [],
        "notes": "来自按品种切分的正文片段",
    }


def _best_segment_for_result(
    result: AnalysisResult,
    product_segments: list[ArticleProductSegment],
) -> ArticleProductSegment | None:
    candidates = [
        segment
        for segment in product_segments
        if (
            (result.product_key and segment.product_key == result.product_key)
            or (not result.product_key and segment.product == result.product)
        ) and segment.section_type != "unknown"
    ]
    if result.contract_key:
        exact = [segment for segment in candidates if segment.contract_key == result.contract_key]
        if exact:
            candidates = exact
    if not candidates:
        return None
    section_priority = {"core": 0, "ocr": 1, "ai": 2, "table": 3, "mixed": 4}
    return sorted(
        candidates,
        key=lambda item: (
            -_segment_reason_score(result, item),
            section_priority.get(item.section_type, 9),
            -float(item.confidence or 0.0),
            item.segment_index,
            item.id or 0,
        ),
    )[0]


def _segment_reason_score(result: AnalysisResult, segment: ArticleProductSegment) -> int:
    reason = _clean_evidence_display_text(result.reason)
    segment_text = clean_display_text(
        "\n".join(value for value in [segment.refined_text, segment.cleaned_text] if value)
    )
    if not segment_text:
        return -100

    score = 0
    if reason and reason in segment_text:
        score += 100
    reason_terms = _evidence_match_terms(reason)
    if reason_terms:
        score += sum(12 for term in reason_terms if term in segment_text)
    if result.direction and result.direction in segment_text:
        score += 4
    if _looks_incomplete_segment(segment_text):
        score -= 80
    return score


def _evidence_match_terms(text: str) -> list[str]:
    terms: list[str] = []
    for part in re.split(r"[。！？；;，,、\n\s]+", text or ""):
        cleaned = _compact_text(part)
        if len(cleaned) >= 4:
            terms.append(cleaned)
    return _dedupe(terms)


def _looks_incomplete_segment(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return True
    if len(compact) < 120 and re.search(r"(跌幅|涨幅|同比|环比|产地|等待|较上周|较昨日|达到)$", compact):
        return True
    return False


def build_analysis_evidence(result: AnalysisResult, article_text: ArticleText | None) -> dict:
    """Build traceable evidence from existing reason/text fields without persistence changes."""
    summary = _clean_evidence_display_text(result.reason)
    cleaned_text = article_text.cleaned_text if article_text and article_text.cleaned_text else ""
    raw_text = article_text.raw_text if article_text and article_text.raw_text else ""

    search_steps = [
        ("cleaned_text", cleaned_text),
        ("raw_text", raw_text),
    ]
    for source, text in search_steps:
        excerpts = _find_product_scoped_evidence_excerpts(text, result, source=source)
        if excerpts:
            return {
                "summary": summary,
                "source": source,
                "excerpts": excerpts,
                "notes": _product_scoped_match_note(source, _primary_match_type(excerpts)),
            }

    if _looks_like_multi_product_text(result, cleaned_text, raw_text):
        return _analysis_reason_evidence(result, summary)

    for source, text in search_steps:
        excerpts = _find_evidence_excerpts(text, _evidence_candidates(result), source=source)
        if excerpts:
            return {
                "summary": summary,
                "source": source,
                "excerpts": excerpts,
                "notes": _match_note(source, _primary_match_type(excerpts)),
            }

    return _analysis_reason_evidence(result, summary)


def _analysis_reason_evidence(result: AnalysisResult, summary: str) -> dict:
    fallback_quote = summary or f"{result.product}{result.direction}，置信度 {result.confidence:.2f}"
    return {
        "summary": summary,
        "source": "analysis_reason",
        "excerpts": [
            {
                "quote": fallback_quote,
                "source": "analysis_reason",
                "start_char": None,
                "end_char": None,
                "match_type": "fallback",
            }
        ] if fallback_quote else [],
        "notes": "未能定位原文，仅展示分析理由",
    }


def _find_product_scoped_evidence_excerpts(
    text: str,
    result: AnalysisResult,
    *,
    source: str,
    limit: int = 3,
) -> list[dict]:
    """Locate fallback evidence near the current product anchor.

    The generic reason matcher is intentionally broad.  In multi-product
    reports, phrases such as “库存加速去化” and “偏弱震荡” appear across many
    products, so a fallback match must first be scoped by the requested product.
    """
    if not text:
        return []

    current_anchors = _find_product_anchor_occurrences(text, _product_anchor_terms(result))
    if not current_anchors:
        return []

    other_boundaries = _find_other_product_boundary_occurrences(text, result)
    candidates = _evidence_candidates(result)
    keyword_fallbacks: list[dict] = []

    for anchor in sorted(current_anchors, key=lambda item: (not item["is_boundary"], item["start"])):
        span_start, span_end = _product_scope_bounds(text, anchor, other_boundaries)
        if span_start >= span_end:
            continue

        scoped_text = text[span_start:span_end]
        excerpts = _find_evidence_excerpts(scoped_text, candidates, source=source, limit=limit)
        if excerpts:
            return [_shift_excerpt(excerpt, span_start) for excerpt in excerpts]

        quote_start, quote_end = _evidence_window(text, anchor["start"], anchor["end"])
        quote_start = max(quote_start, span_start)
        quote_end = min(quote_end, span_end)
        quote = _clean_evidence_display_text(_compact_text(text[quote_start:quote_end]))
        if quote:
            keyword_fallbacks.append(
                {
                    "quote": quote,
                    "source": source,
                    "start_char": quote_start,
                    "end_char": quote_end,
                    "match_type": "keyword",
                }
            )

    return keyword_fallbacks[:limit]


def _shift_excerpt(excerpt: dict, offset: int) -> dict:
    shifted = dict(excerpt)
    if shifted.get("start_char") is not None:
        shifted["start_char"] += offset
    if shifted.get("end_char") is not None:
        shifted["end_char"] += offset
    return shifted


def _product_scope_bounds(text: str, anchor: dict, other_boundaries: list[dict]) -> tuple[int, int]:
    next_other = min(
        (item["start"] for item in other_boundaries if item["start"] > anchor["start"]),
        default=len(text),
    )
    previous_other_end = max(
        (item["end"] for item in other_boundaries if item["end"] <= anchor["start"]),
        default=0,
    )
    if anchor["is_boundary"]:
        start = anchor["start"]
        end = next_other
    elif previous_other_end == 0 and next_other == len(text):
        start = 0
        end = len(text)
    else:
        start, end = _paragraph_window(text, anchor["start"], anchor["end"])
        start = max(start, previous_other_end)
        end = min(end, next_other)
    return _trim_bounds(text, start, end)


def _looks_like_multi_product_text(result: AnalysisResult, *texts: str) -> bool:
    for text in texts:
        if not text:
            continue
        current_anchors = _find_product_anchor_occurrences(text, _product_anchor_terms(result))
        other_boundaries = _find_other_product_boundary_occurrences(text, result)
        if not current_anchors and len({item["product_key"] for item in other_boundaries}) >= 2:
            return True
    return False


def _definition_for_result(result: AnalysisResult) -> ProductDefinition | None:
    definition = get_product(result.product_key)
    if definition is not None:
        return definition
    return get_product(product_key_for_name(result.product))


def _product_anchor_terms(result: AnalysisResult) -> list[str]:
    definition = _definition_for_result(result)
    terms: list[str] = []
    if definition is not None:
        terms.extend([definition.display_name, definition.official_name, *definition.aliases])
        contract_terms = _contract_anchor_terms(definition, result.contract, result.contract_key)
        terms.extend(contract_terms)
    else:
        terms.append(result.product)
        if result.contract:
            terms.append(f"{result.product}{result.contract}")
    return _dedupe(_usable_anchor_term(term) for term in terms)


def _catalog_anchor_terms(definition: ProductDefinition) -> list[str]:
    return _dedupe(
        _usable_anchor_term(term)
        for term in [definition.display_name, definition.official_name, definition.symbol, *definition.aliases]
    )


def _contract_anchor_terms(
    definition: ProductDefinition,
    contract: str | None,
    contract_key: str | None,
) -> list[str]:
    contracts = _dedupe(
        _normalize_contract_suffix(value)
        for value in [contract, contract_key]
        if _normalize_contract_suffix(value)
    )
    terms: list[str] = []
    for contract_value in contracts:
        for prefix in _dedupe([definition.symbol, definition.display_name, *definition.aliases]):
            if prefix:
                terms.append(f"{prefix}{contract_value}")
                terms.append(f"{prefix} {contract_value}")
    return terms


def _normalize_contract_suffix(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.search(r"(\d{2,4})$", raw)
    return match.group(1) if match else raw


def _usable_anchor_term(term: str | None) -> str:
    value = str(term or "").strip()
    if not value:
        return ""
    # Bare one-letter futures symbols (V, L, M, etc.) are too ambiguous for
    # evidence search. They are still used when combined with a contract.
    if len(value) == 1 and value.isascii():
        return ""
    return value


def _find_product_anchor_occurrences(text: str, terms: list[str]) -> list[dict]:
    occurrences: list[dict] = []
    for term in terms:
        for match in _iter_literal_term_matches(text, term):
            occurrences.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "term": match.group(0),
                    "is_boundary": _is_product_boundary_occurrence(text, match.start(), match.end()),
                }
            )
    return _dedupe_anchor_occurrences(occurrences)


def _find_other_product_boundary_occurrences(text: str, result: AnalysisResult) -> list[dict]:
    current_key = (_definition_for_result(result).product_key if _definition_for_result(result) else "") or result.product_key
    occurrences: list[dict] = []
    for definition in PRODUCT_CATALOG:
        if definition.product_key == current_key:
            continue
        for term in _catalog_anchor_terms(definition):
            for match in _iter_literal_term_matches(text, term):
                if not _is_product_boundary_occurrence(text, match.start(), match.end()):
                    continue
                occurrences.append(
                    {
                        "start": match.start(),
                        "end": match.end(),
                        "term": match.group(0),
                        "product_key": definition.product_key,
                        "is_boundary": True,
                    }
                )
    return _dedupe_anchor_occurrences(occurrences)


def _iter_literal_term_matches(text: str, term: str):
    escaped = re.escape(term)
    if _is_ascii_anchor(term):
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?=\d{{2,4}}\s*合约|[^A-Za-z0-9]|$)"
        yield from re.finditer(pattern, text, flags=re.IGNORECASE)
        return
    yield from re.finditer(escaped, text, flags=re.IGNORECASE)


def _is_ascii_anchor(term: str) -> bool:
    return bool(term) and all(char.isascii() and (char.isalnum() or char.isspace()) for char in term)


def _is_product_boundary_occurrence(text: str, start: int, end: int) -> bool:
    previous_index = start - 1
    while previous_index >= 0 and text[previous_index].isspace():
        previous_index -= 1
    previous = text[previous_index] if previous_index >= 0 else ""
    boundary_before = previous_index < 0 or previous in "\n。！？；;【"

    after = text[end : end + 12].lstrip()
    boundary_after = (
        after.startswith(("合约", "：", ":", "】"))
        or bool(re.match(r"^\d{2,4}\s*合约", after))
    )
    return boundary_before and boundary_after


def _dedupe_anchor_occurrences(occurrences: list[dict]) -> list[dict]:
    seen: set[tuple[int, int, str]] = set()
    result: list[dict] = []
    for item in sorted(occurrences, key=lambda value: (value["start"], -(value["end"] - value["start"]))):
        key = (item["start"], item["end"], item.get("product_key", item.get("term", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _reason_candidates(reason: str) -> list[str]:
    if not reason:
        return []
    compact = _compact_text(reason)
    candidates = [compact]
    candidates.extend(
        _compact_text(part)
        for part in re.split(r"[。！？；;，,、\n]", reason)
        if len(_compact_text(part)) >= 4
    )
    return _dedupe(candidates)


def _keyword_candidates(result: AnalysisResult) -> list[str]:
    candidates = [
        result.product,
        result.contract,
        result.direction,
    ]
    if result.reason:
        candidates.extend(_reason_candidates(result.reason)[:3])
    return [item for item in _dedupe(str(value).strip() for value in candidates if value) if item]


def _evidence_candidates(result: AnalysisResult) -> list[tuple[str, str, int]]:
    candidates: list[tuple[str, str, int]] = []
    for candidate in _reason_candidates(result.reason or ""):
        candidates.append((candidate, "reason", 20 + min(len(candidate), 60)))
    for candidate in _keyword_candidates(result):
        candidates.append((candidate, "keyword", 5 + min(len(candidate), 20)))
    return _dedupe_candidate_specs(candidates)


def _find_evidence_excerpts(
    text: str,
    candidates: list[tuple[str, str, int]],
    *,
    source: str,
    limit: int = 3,
) -> list[dict]:
    if not text or not candidates:
        return []

    windows: list[dict] = []
    for candidate, match_type, weight in candidates:
        candidate = _compact_text(candidate)
        if not candidate:
            continue
        index = text.find(candidate)
        matched_text = candidate
        if index < 0 and len(candidate) > 24:
            matched_text = candidate[:24]
            index = text.find(matched_text)
        if index < 0:
            continue

        start, end = _evidence_window(text, index, index + len(matched_text))
        windows.append(
            {
                "score": weight,
                "start_char": start,
                "end_char": end,
                "match_type": match_type,
                "matched_text": matched_text,
            }
        )
    if not windows:
        return []

    merged_windows = _merge_evidence_windows(windows)
    ranked_windows = sorted(
        merged_windows,
        key=lambda item: (-item["score"], item["start_char"], item["end_char"]),
    )

    excerpts: list[dict] = []
    seen_quotes: set[str] = set()
    for window in ranked_windows:
        quote = _clean_evidence_display_text(_compact_text(text[window["start_char"]:window["end_char"]]))
        if not quote or quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        excerpts.append(
            {
                "quote": quote,
                "source": source,
                "start_char": window["start_char"],
                "end_char": window["end_char"],
                "match_type": window["match_type"],
            }
        )
        if len(excerpts) >= limit:
            break
    return sorted(excerpts, key=lambda item: item["start_char"])


def _evidence_window(text: str, start: int, end: int, max_chars: int = 360) -> tuple[int, int]:
    paragraph_start, paragraph_end = _paragraph_window(text, start, end)
    if paragraph_end - paragraph_start <= max_chars:
        return paragraph_start, paragraph_end
    return _sentence_group_window(text, start, end, max_chars=max_chars)


def _paragraph_window(text: str, start: int, end: int) -> tuple[int, int]:
    if "\n" in text:
        line_start = text.rfind("\n", 0, start) + 1
        previous_blank = text.rfind("\n\n", 0, start)
        if previous_blank != -1:
            line_start = previous_blank + 2

        line_end = text.find("\n", end)
        next_blank = text.find("\n\n", end)
        if next_blank != -1:
            line_end = next_blank
        elif line_end == -1:
            line_end = len(text)

        line_end = _extend_colon_ending(text, line_end)
        return _trim_bounds(text, line_start, line_end)

    return _sentence_group_window(text, start, end)


def _sentence_group_window(text: str, start: int, end: int, max_chars: int = 360) -> tuple[int, int]:
    sentences = _sentence_bounds(text)
    selected_index = None
    for index, (sentence_start, sentence_end) in enumerate(sentences):
        if sentence_start <= start < sentence_end or sentence_start < end <= sentence_end:
            selected_index = index
            break
    if selected_index is None:
        return _trim_bounds(text, max(0, start - max_chars // 2), min(len(text), end + max_chars // 2))

    left = selected_index
    right = selected_index
    while right + 1 < len(sentences) and _ends_with_colon(text[sentences[right][0]:sentences[right][1]]):
        right += 1

    while left > 0 and _is_heading_like(text[sentences[left - 1][0]:sentences[left - 1][1]]):
        left -= 1

    while right - left + 1 < 3 and right + 1 < len(sentences):
        candidate_start = sentences[left][0]
        candidate_end = sentences[right + 1][1]
        if candidate_end - candidate_start > max_chars:
            break
        right += 1

    return _trim_bounds(text, sentences[left][0], sentences[right][1])


def _sentence_bounds(text: str) -> list[tuple[int, int]]:
    bounds: list[tuple[int, int]] = []
    sentence_start = 0
    for index, char in enumerate(text):
        if char in "。！？；\n":
            sentence_end = index + 1
            if sentence_end > sentence_start:
                bounds.append((sentence_start, sentence_end))
            sentence_start = sentence_end
    if sentence_start < len(text):
        bounds.append((sentence_start, len(text)))
    return bounds or [(0, len(text))]


def _merge_evidence_windows(windows: list[dict], gap: int = 24) -> list[dict]:
    ordered = sorted(windows, key=lambda item: (item["start_char"], item["end_char"]))
    merged: list[dict] = []
    for window in ordered:
        if not merged or window["start_char"] > merged[-1]["end_char"] + gap:
            merged.append(window.copy())
            continue

        current = merged[-1]
        current["end_char"] = max(current["end_char"], window["end_char"])
        current["score"] += window["score"]
        if current["match_type"] != "reason" and window["match_type"] == "reason":
            current["match_type"] = "reason"
    return merged


def _extend_colon_ending(text: str, end: int) -> int:
    trimmed = text[:end].rstrip()
    if not _ends_with_colon(trimmed):
        return end
    next_line_end = text.find("\n", end + 1)
    if next_line_end == -1:
        return len(text)
    return next_line_end


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _ends_with_colon(text: str) -> bool:
    return text.rstrip().endswith(("：", ":"))


def _is_heading_like(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and (
        _ends_with_colon(stripped)
        or bool(re.match(r"^[一二三四五六七八九十]+[、.．]", stripped))
        or bool(re.match(r"^[（(]?[一二三四五六七八九十0-9]+[）).．、]", stripped))
    )


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_evidence_display_text(text: str | None) -> str:
    """Clean display evidence and drop short dangling sentence fragments."""
    cleaned = clean_display_text(text)
    if not cleaned:
        return ""
    return _drop_dangling_sentence_tail(cleaned)


def _drop_dangling_sentence_tail(text: str) -> str:
    stripped = text.strip()
    if not stripped or stripped.endswith(("。", "！", "？", "；", ".", "!", "?", ";", "”", "’", "」", "』")):
        return stripped

    last_break = max(stripped.rfind(mark) for mark in "。！？；;")
    if last_break < 0:
        return stripped

    tail = stripped[last_break + 1 :].strip()
    if not tail:
        return stripped[: last_break + 1].strip()

    # Product segments may end mid-sentence after page/section slicing. A short
    # final fragment without terminal punctuation is more harmful than helpful
    # in evidence display, while the full source text remains persisted.
    if len(tail) <= 32:
        return stripped[: last_break + 1].strip()
    return stripped


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe_candidate_specs(candidates: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str, int]] = []
    for candidate, match_type, weight in candidates:
        key = (candidate, match_type)
        if candidate and key not in seen:
            seen.add(key)
            result.append((candidate, match_type, weight))
    return result


def _primary_match_type(excerpts: list[dict]) -> str:
    if any(excerpt.get("match_type") == "reason" for excerpt in excerpts):
        return "reason"
    return "keyword"


def _match_note(source: str, match_type: str) -> str:
    source_label = "清洗文本" if source == "cleaned_text" else "原始文本"
    if match_type == "reason":
        return f"由 reason 在{source_label}中定位"
    return f"由品种、合约或方向关键词在{source_label}中定位"


def _product_scoped_match_note(source: str, match_type: str) -> str:
    source_label = "清洗文本" if source == "cleaned_text" else "原始文本"
    if match_type == "reason":
        return f"由品种锚点限定范围后，在{source_label}中按 reason 定位"
    return f"由品种或合约锚点在{source_label}中定位"
