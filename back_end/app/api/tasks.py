"""
任务触发接口 - 提供分析流水线的触发入口，支持单篇处理和批量处理两种模式。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from back_end.app.api.schemas import TaskRunRequest
from back_end.app.core.config import get_settings
from back_end.app.core.database import get_session
from back_end.app.core.responses import success_response
from back_end.app.repositories.articles import ArticleRepository
from back_end.app.tasks.scheduler import create_session_factory
from back_end.app.services.batch import batch_process
from back_end.app.services.pipeline import run_pipeline

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("/run")
def run_task(
    request: TaskRunRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """
    触发分析流水线任务，支持两种模式：

    **模式一：单篇文章处理**
    当请求体中指定 article_id 时，对该文章执行完整的分析流水线（解析→清洗→分析），
    完成后提交或回滚事务。

    **模式二：批量处理待处理文章**
    当请求体中不指定 article_id 时，从数据库查询所有状态为"待处理"的文章，
    使用 batch_process 并发执行流水线（最大并发数 5），每篇文章使用独立的数据库 session。

    Args:
        request: 请求体，可选字段：
            - article_id: 指定单篇文章 ID（可选，指定则进入单篇模式）
            - limit: 批量处理时的最大处理数量（可选，默认取配置 task_batch_size）
        session: 数据库会话（由依赖注入提供）

    Returns:
        dict: 形如 {"code": 200, "data": {...}}，其中 data 包含：
            - triggered:  触发处理的文章数量
            - article_id: 单篇模式时的文章 ID（批量模式为 None）
            - limit:      批量模式时的上限数量（单篇模式为 None）
            - succeeded:  成功处理的文章数
            - failed:     失败处理的文章数
            - message:    状态描述文字
    """
    settings = get_settings()
    payload = request or TaskRunRequest()

    # ---------- 模式一：单篇文章处理 ----------
    if payload.article_id is not None:
        try:
            # 对指定文章执行完整流水线（解析→清洗→分析）
            success = run_pipeline(payload.article_id, session)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return success_response(
            {
                "triggered": 1,
                "article_id": payload.article_id,
                "limit": None,
                "succeeded": 1 if success else 0,
                "failed": 0 if success else 1,
                "message": "Pipeline completed" if success else "Pipeline failed",
            }
        )

    # ---------- 模式二：批量处理 ----------
    # 获取批量处理上限：优先取请求中的 limit，否则使用配置的默认批次大小
    limit = payload.limit or settings.task_batch_size

    # 查询所有待处理文章（不锁定记录，仅获取 ID 列表）
    repository = ArticleRepository(session)
    pending_articles = repository.get_pending_articles(limit=limit, lock=False)
    article_ids = [article.id for article in pending_articles]

    # 没有待处理文章时直接返回
    if not article_ids:
        return success_response(
            {
                "triggered": 0,
                "article_id": None,
                "limit": limit,
                "succeeded": 0,
                "failed": 0,
                "message": "No pending articles",
            }
        )

    # 并发执行批量流水线：每篇文章使用独立 session，最大并发数不超过 5
    result = batch_process(
        article_ids,
        create_session_factory(session.get_bind()),
        max_concurrency=min(len(article_ids), 5),
        pipeline_callback=run_pipeline,
    )
    return success_response(
        {
            "triggered": result.total,
            "article_id": None,
            "limit": limit,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "message": result.summary(),
        }
    )
