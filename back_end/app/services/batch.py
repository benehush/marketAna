"""Small database-safe batch runner used by the task API and scheduler."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class BatchResult:
    total: int
    succeeded: int
    failed: int

    def summary(self) -> str:
        return f"batch completed: total={self.total}, succeeded={self.succeeded}, failed={self.failed}"


def batch_process(
    article_ids: list[int],
    session_factory: Callable[[], Any],
    *,
    max_concurrency: int = 5,
    pipeline_callback: Callable[[int, Any], bool],
) -> BatchResult:
    succeeded = 0
    failed = 0

    def run_one(article_id: int) -> bool:
        session = session_factory()
        try:
            result = pipeline_callback(article_id, session)
            if result:
                session.commit()
            else:
                session.commit()
            return bool(result)
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=max(1, min(max_concurrency, len(article_ids) or 1))) as executor:
        futures = [executor.submit(run_one, article_id) for article_id in article_ids]
        for future in as_completed(futures):
            if future.result():
                succeeded += 1
            else:
                failed += 1
    return BatchResult(total=len(article_ids), succeeded=succeeded, failed=failed)
