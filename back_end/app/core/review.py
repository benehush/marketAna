"""Shared review queue validation and evidence display helpers."""

from __future__ import annotations

import os
import re
from typing import Any

from data_proccessing.llm.diagnostics import LLM_ERROR_TYPES, sanitize_text


REVIEW_REASON_CODES = {
    "navigation_noise": "网页导航误识别",
    "not_futures_product": "非期货品种",
    "no_analysis_content": "无有效分析内容",
    "duplicate": "重复审核项",
    "other": "其他",
}

TRIGGER_REASON_LABELS = {
    "no_signal": "识别到品种，但未找到有效方向信号",
    "no_product_match": "未识别到有效期货品种",
    "related_product_mention_only": "仅在其他品种分析中被提及，不构成独立方向结论",
    "rule_evidence_quality_failed": "规则结论缺少可验证证据",
    "llm_evidence_quality_failed": "大模型结论缺少可验证证据",
    "llm_error_or_invalid_output": "大模型分析失败或返回格式无效",
}

_BOILERPLATE_MARKERS = (
    "无障碍浏览", "客服电话", "公司概括", "公司简介", "组织架构", "股东信息",
    "营业执照", "经营许可证", "企业文化", "联系我们", "加入我们", "社会招聘",
    "校园招聘", "版权所有", "ICP备案", "首页", "网站地图",
)


def trigger_reason_label(reason: str) -> str:
    base = (reason or "unknown").split(":", 1)[0]
    return TRIGGER_REASON_LABELS.get(base, reason or "未知原因")


def evidence_quotes(value: Any) -> list[str]:
    """Extract useful evidence strings from legacy and canonical JSON shapes."""
    candidates: list[str] = []
    if isinstance(value, str):
        candidates.append(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                candidates.append(str(item.get("quote") or item.get("text") or item.get("excerpt") or ""))
    elif isinstance(value, dict):
        excerpts = value.get("excerpts")
        if isinstance(excerpts, list):
            candidates.extend(evidence_quotes(excerpts))
        else:
            candidates.append(str(value.get("quote") or value.get("text") or value.get("excerpt") or value.get("raw") or ""))
    return [quote for quote in (_clean_quote(item) for item in candidates) if quote]


def clean_review_evidence(value: Any) -> dict[str, Any]:
    """Normalize legacy evidence while preserving allow-listed LLM diagnostics."""
    cleaned_excerpts: list[dict[str, Any]] = []
    raw_excerpts = value.get("excerpts") if isinstance(value, dict) else None
    if isinstance(raw_excerpts, list):
        for item in raw_excerpts:
            excerpt = _clean_excerpt(item)
            if excerpt is not None:
                cleaned_excerpts.append(excerpt)
    else:
        cleaned_excerpts = [{"quote": quote} for quote in evidence_quotes(value)]
    cleaned: dict[str, Any] = {"excerpts": cleaned_excerpts}
    if isinstance(value, dict) and value.get("kind") in {"verified", "candidate_context"}:
        cleaned["kind"] = value["kind"]
    if isinstance(value, dict) and str(value.get("notes") or "").strip():
        cleaned["notes"] = sanitize_text(value.get("notes"), limit=500)
    diagnostic = value.get("diagnostic") if isinstance(value, dict) else None
    if isinstance(diagnostic, dict):
        cleaned["diagnostic"] = _clean_diagnostic(diagnostic)
    return cleaned


def _clean_excerpt(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        quote = _clean_quote(value)
        return {"quote": quote} if quote else None
    if not isinstance(value, dict):
        return None
    quote = _clean_quote(str(value.get("quote") or value.get("text") or value.get("excerpt") or ""))
    if not quote:
        return None
    cleaned: dict[str, Any] = {"quote": quote}
    source = str(value.get("source") or "")
    if source in {"segment", "cleaned_text", "raw_text", "analysis_reason", "manual"}:
        cleaned["source"] = source
    for key in ("start_char", "end_char"):
        if value.get(key) is not None:
            cleaned[key] = _non_negative_int(value.get(key))
    match_type = str(value.get("match_type") or "")
    if match_type in {"reason", "keyword", "fallback", "manual", "llm_selected", "context"}:
        cleaned["match_type"] = match_type
    if "validated" in value:
        cleaned["validated"] = bool(value.get("validated"))
    raw_quote = str(value.get("raw_quote") or "")
    if raw_quote:
        cleaned["raw_quote"] = sanitize_text(raw_quote, limit=1200)
    return cleaned


def _clean_diagnostic(value: dict[str, Any]) -> dict[str, Any]:
    secrets = tuple(
        secret
        for secret in (
            os.getenv("DATA_LLM_API_KEY", ""),
            os.getenv("LLM_API_KEY", ""),
        )
        if secret
    )
    error_type = str(value.get("error_type") or "unexpected_error")
    if error_type not in LLM_ERROR_TYPES:
        error_type = "unexpected_error"
    cleaned: dict[str, Any] = {
        "error_type": error_type,
        "message": sanitize_text(value.get("message"), secrets=secrets, limit=1000),
        "parse_errors": [],
        "raw_response_excerpt": sanitize_text(
            value.get("raw_response_excerpt"), secrets=secrets, limit=500
        ),
        "provider": sanitize_text(value.get("provider"), secrets=secrets, limit=64),
        "attempt_count": _non_negative_int(value.get("attempt_count")),
        "transport_retry_count": _non_negative_int(value.get("transport_retry_count")),
        "correction_retry_count": min(1, _non_negative_int(value.get("correction_retry_count"))),
        "retry_exhausted": bool(value.get("retry_exhausted", False)),
    }
    parse_errors = value.get("parse_errors")
    if isinstance(parse_errors, list):
        for item in parse_errors[:10]:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("error_type") or "unexpected_error")
            if item_type not in LLM_ERROR_TYPES:
                item_type = "unexpected_error"
            cleaned["parse_errors"].append(
                {
                    "phase": "correction" if item.get("phase") == "correction" else "initial",
                    "error_type": item_type,
                    "field": sanitize_text(item.get("field"), secrets=secrets, limit=80),
                    "message": sanitize_text(item.get("message"), secrets=secrets, limit=1000),
                    "value_excerpt": sanitize_text(item.get("value_excerpt"), secrets=secrets, limit=120),
                }
            )
    for key in ("http_status", "sse_line_count"):
        if value.get(key) is not None:
            cleaned[key] = _non_negative_int(value.get(key))
    if value.get("content_type"):
        cleaned["content_type"] = sanitize_text(value.get("content_type"), secrets=secrets, limit=200)
    samples = value.get("sse_event_samples")
    if isinstance(samples, list):
        cleaned["sse_event_samples"] = [
            sanitize_text(item, secrets=secrets, limit=300) for item in samples[:3]
        ]
    if value.get("done_received") is not None:
        cleaned["done_received"] = bool(value.get("done_received"))
    return cleaned


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _clean_quote(value: str) -> str:
    quote = re.sub(r"\s+", " ", str(value or "")).strip()
    if not quote:
        return ""
    if re.fullmatch(r"[a-z_][a-z0-9_:-]*", quote, flags=re.IGNORECASE):
        return ""
    marker_count = sum(marker in quote for marker in _BOILERPLATE_MARKERS)
    if marker_count >= 2 or ("无障碍浏览" in quote and "客服电话" in quote):
        return ""
    return quote[:1200]
