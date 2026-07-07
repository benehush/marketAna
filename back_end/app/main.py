from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from back_end.app.api.articles import router as articles_router
from back_end.app.api.companies import router as companies_router
from back_end.app.api.dashboard import router as dashboard_router
from back_end.app.api.health import router as health_router
from back_end.app.api.products import router as products_router
from back_end.app.api.results import router as results_router
from back_end.app.api.tasks import router as tasks_router
from back_end.app.api.trends import router as trends_router
from back_end.app.core.config import get_settings
from back_end.app.core.database import get_engine
from back_end.app.core.exceptions import register_exception_handlers
from back_end.app.core.logging import setup_logging
from back_end.app.tasks.scheduler import create_scheduler, create_session_factory


# 应用启动时的 FastAPI 应用实例，确保在其他模块中可以访问
# 应用结束时，确保数据库连接和调度器被正确关闭
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = None
    scheduler = None

    if settings.database_url:
        engine = get_engine()
        scheduler = create_scheduler(
            settings,
            session_factory=create_session_factory(engine),
        )
        scheduler.start()
        app.state.article_scheduler = scheduler

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()
        if engine is not None:
            engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(dashboard_router)
    app.include_router(articles_router)
    app.include_router(products_router)
    app.include_router(companies_router)
    app.include_router(trends_router)
    app.include_router(tasks_router)
    app.include_router(results_router)
    return app

# 创建 FastAPI 应用实例
app = create_app()
