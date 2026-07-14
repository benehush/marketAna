"""Transactional adapter from the standalone canonical result to ORM models."""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from data_proccessing.pipeline import validate_canonical_result
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.core.dates import valid_publish_time
from back_end.app.core.review import clean_review_evidence
from back_end.app.models import AnalysisResult, AnalysisReviewQueue, Article
from back_end.app.repositories.articles import ArticleRepository


def ingest_canonical_result(
    session: Session,
    payload: dict[str, Any],
    *,
    article_id: int | None = None,
) -> dict[str, Any]:
    """Import one canonical result without committing the caller's transaction."""
    validate_canonical_result(payload)
    document = payload["document"]
    source_id = str(payload["source_id"]).strip()
    article = _find_or_create_article(session, source_id, document, article_id=article_id)
    repo = ArticleRepository(session)

    raw_text = str(document.get("raw_text") or "")
    cleaned_text = str(document.get("cleaned_text") or raw_text)
    if raw_text or article.text is None:
        repo.save_raw_text(article.id, raw_text, parser_type=str(document.get("file_type") or "unknown"))
    repo.save_cleaned_text(article.id, cleaned_text)

    result_rows = list(payload.get("results") or [])
    segment_rows = [_segment_from_result(item, cleaned_text) for item in result_rows]
    if segment_rows:
        repo.save_product_segments(article.id, segment_rows)
    saved_results = repo.save_analysis_results(article.id, result_rows, mark_stored=False)
    _reconcile_analysis_results(session, article.id, result_rows)

    review_rows = list(payload.get("review_queue") or [])
    active_review_keys = {_upsert_review_item(session, article.id, item) for item in review_rows}
    _reconcile_pending_review_items(session, article.id, active_review_keys)

    repo.save_task_log(
        article_id=article.id,
        stage="canonical_import",
        status="success" if not payload.get("processing_stats", {}).get("error_count") else "partial",
        message=_stats_message(payload),
        duration_ms=_duration_ms(payload),
    )
    repo.update_status(article.id, ArticleProcessingStatus.STORED)
    session.flush()
    return {
        "article_id": article.id,
        "source_id": source_id,
        "result_count": len(saved_results),
        "review_count": len(review_rows),
        "pipeline_version": payload.get("pipeline_version", ""),
    }


def _find_or_create_article(
    session: Session,
    source_id: str,
    document: dict[str, Any],
    *,
    article_id: int | None,
) -> Article:
    if article_id is not None:
        article = session.get(Article, article_id)
        if article is None:
            raise ValueError(f"article_id {article_id} does not exist")
        return article
    article = session.scalar(select(Article).where(Article.file_url == source_id))
    if article is not None:
        return article
    publish_time = _parse_datetime(document.get("publish_time"))
    article = Article(
        title=str(document["title"]).strip(),
        source=_optional_text(document.get("source")),
        company=_optional_text(document.get("company")),
        file_url=source_id,
        file_type=_normalize_file_type(document.get("file_type")),
        publish_time=publish_time,
    )
    session.add(article)
    session.flush()
    return article


def _segment_from_result(item: dict[str, Any], cleaned_text: str) -> dict[str, Any]:
    evidence = item.get("evidence") or {}
    excerpts = evidence.get("excerpts") if isinstance(evidence, dict) else []
    excerpts = excerpts if isinstance(excerpts, list) else []
    quote = "\n".join(str(row.get("quote") or "").strip() for row in excerpts if isinstance(row, dict)).strip()
    first = next((row for row in excerpts if isinstance(row, dict)), {})
    return {
        "product": item.get("product") or item["product_key"],
        "product_key": item["product_key"],
        "contract": item.get("contract"),
        "contract_key": item.get("contract_key") or "",
        "cleaned_text": quote or cleaned_text[:600],
        "start_char": first.get("start_char"),
        "end_char": first.get("end_char"),
        "section_type": evidence.get("section_type", "core") if isinstance(evidence, dict) else "core",
        "confidence": item.get("confidence", 0.0),
        "resolution_method": "canonical",
        "resolution_confidence": item.get("confidence", 0.0),
    }


def _upsert_review_item(session: Session, article_id: int, item: dict[str, Any]) -> str:
    product_key = str(item.get("product_key") or "")
    reason = str(item.get("reason") or "unknown")
    fingerprint = hashlib.sha1(
        f"{article_id}|{product_key}|{reason}|{item.get('start_char', '')}".encode("utf-8")
    ).hexdigest()
    row = session.scalar(
        select(AnalysisReviewQueue).where(
            AnalysisReviewQueue.article_id == article_id,
            AnalysisReviewQueue.item_key == fingerprint,
        )
    )
    if row is None:
        row = AnalysisReviewQueue(article_id=article_id, item_key=fingerprint)
        session.add(row)
    elif row.status in {"rejected", "resolved"}:
        # A human decision is terminal. Re-running the same pipeline item may
        # refresh neither its status nor its audit metadata.
        return fingerprint
    row.product_key = product_key or None
    row.product = _optional_text(item.get("product"))
    row.reason = reason[:128]
    row.evidence_json = clean_review_evidence(item.get("evidence"))
    row.status = "pending"
    return fingerprint


def _reconcile_pending_review_items(session: Session, article_id: int, active_keys: set[str]) -> None:
    pending_rows = list(
        session.scalars(
            select(AnalysisReviewQueue).where(
                AnalysisReviewQueue.article_id == article_id,
                AnalysisReviewQueue.status == "pending",
            )
        ).all()
    )
    for row in pending_rows:
        if row.item_key not in active_keys:
            session.delete(row)


def _reconcile_analysis_results(
    session: Session,
    article_id: int,
    result_rows: list[dict[str, Any]],
) -> None:
    active_keys = {
        (str(item.get("product_key") or ""), str(item.get("contract_key") or ""))
        for item in result_rows
    }
    existing_rows = list(
        session.scalars(select(AnalysisResult).where(AnalysisResult.article_id == article_id)).all()
    )
    for row in existing_rows:
        if row.analysis_method == "manual":
            continue
        if (row.product_key, row.contract_key or "") not in active_keys:
            session.delete(row)


def _stats_message(payload: dict[str, Any]) -> str:
    stats = payload.get("processing_stats") or {}
    return "canonical import: " + ", ".join(
        f"{key}={stats[key]}"
        for key in (
            "matched_products",
            "signal_count",
            "rule_results",
            "llm_results",
            "error_count",
            "llm_retry_count",
            "llm_recovered_count",
        )
        if key in stats
    )


def _duration_ms(payload: dict[str, Any]) -> int | None:
    value = (payload.get("processing_stats") or {}).get("duration_ms")
    return int(value) if isinstance(value, (int, float)) else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    normalized = parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    return valid_publish_time(normalized)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_file_type(value: Any) -> str:
    value = str(value or "txt").lower().lstrip(".")
    return "image" if value in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"} else value
