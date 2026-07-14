from collections.abc import Callable

from back_end.app.core.config import Settings, get_settings
from back_end.app.core.database import get_engine
from apscheduler.schedulers.background import BackgroundScheduler
from back_end.app.services.pipeline import run_pipeline
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(engine: Engine | None = None) -> Callable[[], Session]:
    """Create independent SQLAlchemy sessions for scheduler and batch jobs."""
    resolved_engine = engine or get_engine()
    factory = sessionmaker(
        bind=resolved_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return factory


class Scheduler:
    """Minimal scheduler facade with no dependency on legacy pn modules."""

    def __init__(self, session_factory, pipeline_callback=run_pipeline, *, batch_size=20, poll_interval_seconds=300, timezone="Asia/Shanghai"):
        self._session_factory = session_factory
        self._pipeline_callback = pipeline_callback
        self._batch_size = batch_size
        self._scheduler = BackgroundScheduler(timezone=timezone)
        self._scheduler.add_job(self.scan_and_dispatch, "interval", seconds=poll_interval_seconds, id="article_pipeline", replace_existing=True)
        self._running = False

    def scan_and_dispatch(self):
        from back_end.app.repositories.articles import ArticleRepository
        session = self._session_factory()
        try:
            repo = ArticleRepository(session)
            articles = repo.get_pending_articles(self._batch_size, lock=True)
            succeeded = failed = 0
            for article in articles:
                if self._pipeline_callback(article.id, session):
                    succeeded += 1
                else:
                    failed += 1
            session.commit()
            return {"scanned": len(articles), "triggered": len(articles), "succeeded": succeeded, "failed": failed}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def start(self):
        if not self._running:
            self._scheduler.start()
            self._running = True

    def stop(self, *, wait=True):
        if self._running:
            self._scheduler.shutdown(wait=wait)
            self._running = False

    @property
    def is_running(self):
        return self._running


def create_scheduler(
    settings: Settings | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> Scheduler:
    """Create the real article pipeline scheduler."""
    resolved_settings = settings or get_settings()
    return Scheduler(
        session_factory=session_factory or create_session_factory(),
        pipeline_callback=run_pipeline,
        batch_size=resolved_settings.task_batch_size,
        poll_interval_seconds=resolved_settings.scheduler_poll_interval_seconds,
        timezone="Asia/Shanghai",
    )
