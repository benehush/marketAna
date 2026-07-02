from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from back_end.app.core.config import get_settings
from back_end.app.core.exceptions import AppException, ErrorCode

# 提供/home/sanmu/marketANA/plan_details/p1_init.md
class Base(DeclarativeBase):
    pass

# 创建引擎（Engine） — 管理连接池

def build_engine(database_url: str | None) -> Engine | None:
    if not database_url:
        return None

    url = make_url(database_url)
    connect_args = {}
    if url.drivername.startswith("mysql"):
        connect_args["connect_timeout"] = 2

    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)



def check_database_connection(database_url: str | None = None) -> str:
    if not database_url:
        return "unconfigured"

    try:
        engine = build_engine(database_url)
        if engine is None:
            return "unconfigured"
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return "ok"
    except SQLAlchemyError:
        return "error"


def get_engine() -> Engine:
    engine = build_engine(get_settings().database_url)
    if engine is None:
        raise AppException(
            code=ErrorCode.DATABASE_UNCONFIGURED,
            message="Database URL is not configured",
        )
    return engine


def get_session() -> Generator[Session, None, None]:
    session_factory = sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    with session_factory() as session:
        yield session
