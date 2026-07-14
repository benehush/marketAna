"""Article-level work queue assembled from review items and task logs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from back_end.app.core.review import evidence_quotes, trigger_reason_label
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import Article


QUEUE_TABS = ("pending", "completed", "rejected", "error")


class ReviewQueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_queue(self, *, tab: str, company: str | None = None, product_key: str | None = None,
                   reason: str | None = None, keyword: str | None = None,
                   missing_evidence: bool = False, sort: str | None = None,
                   page: int = 1, page_size: int = 20) -> dict[str, Any]:
        articles = list(self.session.scalars(
            select(Article).options(
                selectinload(Article.review_queue), selectinload(Article.task_logs)
            ).where(
                (Article.status == ArticleProcessingStatus.FAILED.value) | Article.review_queue.any()
            )
        ).all())
        classified = [(article, self._classify(article)) for article in articles]
        classified = [(article, category) for article, category in classified if category is not None]
        filter_options = self._filter_options(classified)
        filtered = [(article, category) for article, category in classified if self._matches_filters(
            article, company=company, product_key=product_key, reason=reason,
            keyword=keyword, missing_evidence=missing_evidence,
        )]
        counts = {name: sum(category == name for _, category in filtered) for name in QUEUE_TABS}
        selected = [article for article, category in filtered if category == tab]
        selected.sort(key=lambda article: self._sort_key(article, tab, sort))
        total = len(selected)
        selected = selected[(page - 1) * page_size: page * page_size]
        return {"items": [self._serialize(article, tab) for article in selected], "total": total,
                "counts": counts, "filter_options": filter_options}

    @staticmethod
    def _latest_pipeline_log(article: Article):
        logs = [log for log in article.task_logs if log.stage == "pipeline"]
        return max(logs, key=lambda log: log.id or 0) if logs else None

    def _classify(self, article: Article) -> str | None:
        latest = self._latest_pipeline_log(article)
        if article.status == ArticleProcessingStatus.FAILED.value or (
            latest is not None and latest.status in {"failed", "partial"}
        ):
            return "error"
        statuses = [item.status for item in article.review_queue]
        if "pending" in statuses:
            return "pending"
        if "resolved" in statuses:
            return "completed"
        if statuses and all(status == "rejected" for status in statuses):
            return "rejected"
        return None

    @staticmethod
    def _matches_filters(article: Article, *, company: str | None, product_key: str | None,
                         reason: str | None, keyword: str | None, missing_evidence: bool) -> bool:
        if company and (article.company or article.source or "") != company:
            return False
        if product_key and not any(item.product_key == product_key for item in article.review_queue):
            return False
        if reason and not any(item.reason == reason for item in article.review_queue):
            return False
        if keyword:
            needles = keyword.strip().lower().split()
            haystack = f"{article.title} {article.company or ''} {article.source or ''}".lower()
            if not all(needle in haystack for needle in needles):
                return False
        if missing_evidence and not any(not evidence_quotes(item.evidence_json) for item in article.review_queue):
            return False
        return True

    def _sort_key(self, article: Article, tab: str, sort: str | None):
        pending = [item for item in article.review_queue if item.status == "pending"]
        created = min((item.created_at for item in pending), default=article.created_at)
        reviewed = max((item.reviewed_at for item in article.review_queue if item.reviewed_at), default=article.updated_at)
        latest = self._latest_pipeline_log(article)
        error_time = latest.created_at if latest is not None else article.updated_at
        if sort == "oldest":
            return (created, article.id)
        if sort == "newest":
            return (-reviewed.timestamp(), -article.id)
        if tab == "pending":
            return (-len(pending), created, article.id)
        if tab == "error":
            return (-error_time.timestamp(), -article.id)
        return (-reviewed.timestamp(), -article.id)

    def _serialize(self, article: Article, tab: str) -> dict[str, Any]:
        statuses = {name: [item for item in article.review_queue if item.status == name]
                    for name in ("pending", "resolved", "rejected")}
        preferred = statuses.get(tab, [])
        if tab == "completed": preferred = statuses["resolved"]
        if tab == "error": preferred = statuses["pending"] or list(article.review_queue)
        first = sorted(preferred or article.review_queue, key=lambda item: item.id or 0)[0] if article.review_queue else None
        quotes = evidence_quotes(first.evidence_json) if first is not None else []
        latest = self._latest_pipeline_log(article)
        products: dict[str, str] = {}
        for item in article.review_queue:
            if item.product_key: products[item.product_key] = item.product or item.product_key
        entered_at = min((item.created_at for item in article.review_queue), default=article.created_at)
        reviewed_at = max((item.reviewed_at for item in article.review_queue if item.reviewed_at), default=None)
        return {
            "id": article.id, "title": article.title,
            "company": article.company or article.source or "",
            "publish_time": article.publish_time.date().isoformat() if article.publish_time else None,
            "status": tab, "counts": {name: len(items) for name, items in statuses.items()},
            "products": [{"product_key": key, "product": name} for key, name in sorted(products.items())],
            "trigger_reason": first.reason if first else None,
            "trigger_reason_label": trigger_reason_label(first.reason) if first else None,
            "evidence_excerpt": quotes[0] if quotes else None, "missing_evidence": not bool(quotes),
            "evidence_kind": (
                first.evidence_json.get("kind")
                if first is not None and isinstance(first.evidence_json, dict)
                else None
            ),
            "entered_at": entered_at.isoformat() if entered_at else None,
            "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
            "latest_task": {"status": latest.status, "message": latest.message,
                            "created_at": latest.created_at.isoformat()} if latest else None,
        }

    @staticmethod
    def _filter_options(classified: list[tuple[Article, str]]) -> dict[str, Any]:
        companies = sorted({article.company or article.source for article, _ in classified if article.company or article.source})
        products: dict[str, str] = {}; reasons: dict[str, str] = {}
        for article, _ in classified:
            for item in article.review_queue:
                if item.product_key: products[item.product_key] = item.product or item.product_key
                reasons[item.reason] = trigger_reason_label(item.reason)
        return {"companies": companies,
                "products": [{"product_key": key, "product": value} for key, value in sorted(products.items())],
                "reasons": [{"reason": key, "label": value} for key, value in sorted(reasons.items())]}
