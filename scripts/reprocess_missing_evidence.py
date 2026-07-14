"""Preview or reprocess pending review items that have no displayable evidence."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from back_end.app.core.database import get_engine
from back_end.app.core.review import evidence_quotes
from back_end.app.models import AnalysisReviewQueue, Article
from back_end.app.services.batch import batch_process
from back_end.app.services.pipeline import run_pipeline
from back_end.app.tasks.scheduler import create_session_factory


ELIGIBLE_REASONS = {
    "rule_evidence_quality_failed",
    "llm_evidence_quality_failed",
    "llm_error_or_invalid_output",
}


def find_article_ids(*, limit: int) -> list[int]:
    factory = create_session_factory(get_engine())
    session = factory()
    try:
        rows = session.execute(
            select(
                AnalysisReviewQueue.article_id,
                AnalysisReviewQueue.reason,
                AnalysisReviewQueue.evidence_json,
            )
            .join(Article, Article.id == AnalysisReviewQueue.article_id)
            .where(AnalysisReviewQueue.status == "pending")
            .order_by(AnalysisReviewQueue.article_id, AnalysisReviewQueue.id)
        ).all()
        selected: list[int] = []
        seen: set[int] = set()
        for article_id, reason, evidence in rows:
            if str(reason or "").split(":", 1)[0] not in ELIGIBLE_REASONS:
                continue
            if evidence_quotes(evidence) or article_id in seen:
                continue
            selected.append(int(article_id))
            seen.add(int(article_id))
            if len(selected) >= limit:
                break
        return selected
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only list matching article IDs (default).")
    mode.add_argument("--apply", action="store_true", help="Re-run the matching articles.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of articles to inspect.")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent pipeline runs when applying.")
    args = parser.parse_args()
    if args.limit < 1 or args.concurrency < 1:
        parser.error("--limit and --concurrency must be positive integers")

    article_ids = find_article_ids(limit=args.limit)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "article_ids": article_ids}, ensure_ascii=False))
    if not args.apply or not article_ids:
        return 0

    engine = get_engine()
    result = batch_process(
        article_ids,
        create_session_factory(engine),
        max_concurrency=args.concurrency,
        pipeline_callback=run_pipeline,
    )
    print(json.dumps({"total": result.total, "succeeded": result.succeeded, "failed": result.failed}, ensure_ascii=False))
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
