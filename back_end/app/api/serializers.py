import re

from back_end.app.api.schemas import datetime_to_iso
from back_end.app.core.display import is_displayable_analysis_result
from back_end.app.models import AnalysisResult, Article, ArticleText, ManualConfirmation, TaskLog


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
) -> dict | None:
    if result is None:
        return None
    return {
        "id": result.id,
        "article_id": result.article_id,
        "product": result.product,
        "contract": result.contract,
        "contract_key": result.contract_key,
        "direction": result.direction,
        "reason": result.reason,
        "confidence": result.confidence,
        "analysis_method": result.analysis_method,
        "need_manual_review": result.need_manual_review,
        "is_primary": result.is_primary,
        "model_name": result.model_name,
        "llm_duration_ms": result.llm_duration_ms,
        "llm_retry_count": result.llm_retry_count,
        "llm_error_msg": result.llm_error_msg,
        "analysis_time": datetime_to_iso(result.analysis_time),
        "evidence": build_analysis_evidence(result, article_text),
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
        "direction": result.direction if result else None,
        "reason": result.reason if result else None,
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
        "original_direction": confirmation.original_direction,
        "original_reason": confirmation.original_reason,
        "original_confidence": confirmation.original_confidence,
        "confirmed_product": confirmation.confirmed_product,
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
        "analysis_result": serialize_analysis_result(analysis_result, article_text=article.text),
        "analysis_results": [
            serialize_analysis_result(result, article_text=article.text)
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
    }


def build_analysis_evidence(result: AnalysisResult, article_text: ArticleText | None) -> dict:
    """Build traceable evidence from existing reason/text fields without persistence changes."""
    summary = (result.reason or "").strip()
    cleaned_text = article_text.cleaned_text if article_text and article_text.cleaned_text else ""
    raw_text = article_text.raw_text if article_text and article_text.raw_text else ""

    search_steps = [
        ("cleaned_text", cleaned_text),
        ("raw_text", raw_text),
    ]
    for source, text in search_steps:
        excerpts = _find_evidence_excerpts(text, _evidence_candidates(result), source=source)
        if excerpts:
            return {
                "summary": summary,
                "source": source,
                "excerpts": excerpts,
                "notes": _match_note(source, _primary_match_type(excerpts)),
            }

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
        quote = _compact_text(text[window["start_char"]:window["end_char"]])
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
