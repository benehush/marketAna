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
        "raw_length": article_text.raw_length,
        "cleaned_length": article_text.cleaned_length,
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
        ("cleaned_text", cleaned_text, _reason_candidates(summary), "reason"),
        ("cleaned_text", cleaned_text, _keyword_candidates(result), "keyword"),
        ("raw_text", raw_text, _reason_candidates(summary), "reason"),
        ("raw_text", raw_text, _keyword_candidates(result), "keyword"),
    ]
    for source, text, candidates, match_type in search_steps:
        excerpts = _find_evidence_excerpts(text, candidates, source=source, match_type=match_type)
        if excerpts:
            return {
                "summary": summary,
                "source": source,
                "excerpts": excerpts,
                "notes": _match_note(source, match_type),
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
        if len(_compact_text(part)) >= 6
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


def _find_evidence_excerpts(
    text: str,
    candidates: list[str],
    *,
    source: str,
    match_type: str,
    limit: int = 3,
) -> list[dict]:
    if not text or not candidates:
        return []

    excerpts: list[dict] = []
    seen_quotes: set[str] = set()
    for candidate in candidates:
        candidate = _compact_text(candidate)
        if not candidate:
            continue
        index = text.find(candidate)
        if index < 0 and len(candidate) > 24:
            index = text.find(candidate[:24])
        if index < 0:
            continue

        start, end = _sentence_window(text, index, index + len(candidate))
        quote = _compact_text(text[start:end])
        if not quote or quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        excerpts.append(
            {
                "quote": quote,
                "source": source,
                "start_char": start,
                "end_char": end,
                "match_type": match_type,
            }
        )
        if len(excerpts) >= limit:
            break
    return excerpts


def _sentence_window(text: str, start: int, end: int, radius: int = 80) -> tuple[int, int]:
    left_bound = max(0, start - radius)
    right_bound = min(len(text), end + radius)
    left_candidates = [text.rfind(mark, 0, start) for mark in "。！？；\n"]
    left = max(left_candidates)
    if left == -1 or left < left_bound:
        left = left_bound
    else:
        left += 1

    right_candidates = [idx for mark in "。！？；\n" if (idx := text.find(mark, end)) != -1]
    right = min(right_candidates) + 1 if right_candidates else right_bound
    if right > right_bound:
        right = right_bound
    return left, right


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


def _match_note(source: str, match_type: str) -> str:
    source_label = "清洗文本" if source == "cleaned_text" else "原始文本"
    if match_type == "reason":
        return f"由 reason 在{source_label}中定位"
    return f"由品种、合约或方向关键词在{source_label}中定位"
