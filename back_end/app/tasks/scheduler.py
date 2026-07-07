from collections.abc import Callable

from back_end.app.core.config import Settings, get_settings
from back_end.app.core.database import get_engine
from pn03 import Scheduler
from pn11 import run_pipeline
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
