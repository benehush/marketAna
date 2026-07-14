"""
pn11 批量并发处理

使用 ThreadPoolExecutor 并发处理多篇文章，
每篇文章使用独立 Session，限制最大并发数。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from pn11.models import BatchResult, PipelineResult

logger = logging.getLogger(__name__)

__all__ = ["batch_process"]


def batch_process(
    article_ids: list[int],
    session_factory: Callable[[], Any],
    *,
    max_concurrency: int = 5,
    pipeline_callback: Callable[[int, Any], bool] | None = None,
) -> BatchResult:
    """
    批量并发处理文章列表。

    每篇文章使用独立 Session → 独立事务，
    彼此不互相阻塞。通过 max_concurrency 限制并发数。

    Args:
        article_ids: 待处理文章 ID 列表
        session_factory: 返回 SQLAlchemy Session 的可调用对象
        max_concurrency: 最大并发数（默认 5）
        pipeline_callback: 单篇处理回调，默认使用 pn11.pipeline.run_pipeline

    Returns:
        BatchResult: 包含每篇结果和汇总统计
    """
    if pipeline_callback is None:
        from pn11.pipeline import run_pipeline as pipeline_callback

    if not article_ids:
        return BatchResult(total=0, succeeded=0, failed=0)

    start_time = time.monotonic()
    results: list[PipelineResult] = []
    succeeded = 0
    failed = 0

    effective_max_concurrency = _effective_max_concurrency(session_factory, max_concurrency)

    logger.info(
        "批量处理开始: %d 篇文章, 最大并发=%d",
        len(article_ids), effective_max_concurrency,
    )

    # 每篇文章在工作线程中独立处理
    def _process_one(aid: int) -> PipelineResult:
        session = session_factory()
        try:
            success = pipeline_callback(aid, session)
            session.commit()

            # 读取最终状态
            from back_end.app.repositories.articles import ArticleRepository
            repo = ArticleRepository(session)
            article = repo.get_article(aid)

            return PipelineResult(
                article_id=aid,
                success=success,
                start_status=0,
                final_status=article.status if article else -1,
                stages_run=[],
                error_stage="" if success else "unknown",
            )
        except Exception as exc:
            session.rollback()
            return PipelineResult(
                article_id=aid,
                success=False,
                start_status=0,
                final_status=-1,
                error_stage="batch",
                error_message=str(exc),
            )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=effective_max_concurrency) as executor:
        futures = {executor.submit(_process_one, aid): aid for aid in article_ids}

        for future in as_completed(futures):
            aid = futures[future]
            try:
                result = future.result()
                results.append(result)
                if result.success:
                    succeeded += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                results.append(PipelineResult(
                    article_id=aid,
                    success=False,
                    start_status=0,
                    final_status=-1,
                    error_stage="future",
                    error_message=str(exc),
                ))
                logger.exception("batch: article_id=%s future 异常", aid)

    total_ms = int((time.monotonic() - start_time) * 1000)
    batch_result = BatchResult(
        total=len(article_ids),
        succeeded=succeeded,
        failed=failed,
        results=results,
        total_duration_ms=total_ms,
    )

    logger.info("批量处理完成: %s", batch_result.summary())
    return batch_result


def _effective_max_concurrency(session_factory: Callable[[], Any], requested: int) -> int:
    """Avoid unsafe threaded writes on in-memory SQLite StaticPool test engines."""
    requested = max(1, int(requested or 1))
    bind = getattr(session_factory, "_engine", None)
    if bind is None:
        bind = getattr(session_factory, "kw", {}).get("bind")
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    pool_name = type(getattr(bind, "pool", None)).__name__
    if dialect == "sqlite" and pool_name == "StaticPool":
        return 1
    return requested
