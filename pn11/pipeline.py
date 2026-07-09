"""
pn11 流水线核心编排

run_pipeline(article_id, session) 是 pn03 Scheduler 的 pipeline_callback。
按文章当前状态路由到对应 pn04-pn07 阶段，阻塞阶段失败即停止。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from back_end.app.core.status import ArticleProcessingStatus
from pn11.models import PipelineResult

logger = logging.getLogger(__name__)

__all__ = ["run_pipeline"]

# 状态 → 阶段映射
_STATUS_STAGE: dict[int, str] = {
    0: "parser",
    1: "cleaner",
    2: "rule_engine",
    3: "llm_infer",
    5: "stored",
    -1: "failed",
}


def run_pipeline(article_id: int, session: Any) -> bool:
    """
    流水线主入口，作为 pn03 Scheduler 的 pipeline_callback。

    按 article.status 决定从哪个阶段开始：
      status=0  → 从头: parser→cleaner→refiner→rule_engine→(llm_infer)
      status=1  → 续跑: cleaner→refiner→rule_engine→(llm_infer)
      status=2  → 续跑: refiner→rule_engine→(llm_infer)
      status=3  → 续跑: llm_infer
      status=5  → 已完成，跳过
      status=-1 → 根据 error_msg 判断从哪个阶段重试

    每个阶段内部已处理自己的 task_log 和异常→mark_failed。
    pn11 只负责编排和总耗时统计。

    Args:
        article_id: 文章 ID
        session: SQLAlchemy Session

    Returns:
        True: 流水线成功完成（文章已入库 status=5）
        False: 某阶段失败
    """
    from back_end.app.repositories.articles import ArticleRepository

    repo = ArticleRepository(session)
    start_time = time.monotonic()

    # 读取当前状态
    article = repo.get_article(article_id)
    if article is None:
        logger.error("pipeline: article_id=%s 不存在", article_id)
        return False

    current_status = article.status
    error_msg = article.error_msg or ""

    result = PipelineResult(
        article_id=article_id,
        success=False,
        start_status=current_status,
        final_status=current_status,
    )

    logger.info(
        "pipeline 开始 article_id=%s start_status=%s(%s)",
        article_id, current_status,
        _STATUS_STAGE.get(current_status, "unknown"),
    )

    try:
        # ---- status=5: 已完成，跳过 ----
        if current_status == ArticleProcessingStatus.STORED:
            result.success = True
            result.final_status = current_status
            result.stages_run = ["skipped(stored)"]
            result.total_duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info("pipeline article_id=%s 已入库，跳过", article_id)
            return True

        # ---- status=-1: 重试 ----
        if current_status == ArticleProcessingStatus.FAILED:
            retry_from = _resolve_retry_stage(error_msg)
            logger.info("pipeline article_id=%s 从失败重试: %s", article_id, retry_from)
            # 重置为对应阶段的前置状态
            if retry_from == "parser":
                repo.update_status(article_id, ArticleProcessingStatus.PENDING)
                session.refresh(article)
                current_status = 0
            elif retry_from == "cleaner":
                repo.update_status(article_id, ArticleProcessingStatus.PARSED)
                session.refresh(article)
                current_status = 1
            elif retry_from == "refiner":
                repo.update_status(article_id, ArticleProcessingStatus.CLEANED)
                session.refresh(article)
                current_status = 2
            elif retry_from == "rule_engine":
                repo.update_status(article_id, ArticleProcessingStatus.CLEANED)
                session.refresh(article)
                current_status = 2
            elif retry_from == "llm_infer":
                repo.update_status(article_id, ArticleProcessingStatus.RULE_ANALYZED)
                session.refresh(article)
                current_status = 3

        # ---- 按状态路由 ----
        # status=0: PENDING → parser
        if article.status == ArticleProcessingStatus.PENDING:
            _run_parser(article, session, result)
            session.refresh(article)

        # status=1: PARSED → cleaner
        if article.status == ArticleProcessingStatus.PARSED:
            _run_cleaner(article_id, session, result)
            session.refresh(article)

        # status=2: CLEANED → refiner(best-effort) → rule_engine
        if article.status == ArticleProcessingStatus.CLEANED:
            _run_refiner(article_id, session, result)
            session.refresh(article)
            need_llm = _run_rule_engine(article_id, session, result)
            session.refresh(article)
            if not need_llm:
                # 高置信，已直接入库
                result.success = True
                result.final_status = ArticleProcessingStatus.STORED
                result.total_duration_ms = int((time.monotonic() - start_time) * 1000)
                _write_overview_log(repo, article_id, result)
                return True

        # status=3: RULE_ANALYZED → llm_infer
        if article.status == ArticleProcessingStatus.RULE_ANALYZED:
            _run_llm_infer(article_id, session, result)

        # 最终验证
        session.refresh(article)
        result.final_status = article.status
        result.success = article.status == ArticleProcessingStatus.STORED

        if not result.success:
            result.error_stage = "pipeline"
            result.error_message = f"流水线未完成，最终状态={article.status}"

    except Exception as exc:
        # 各阶段已内部 mark_failed，这里只记录
        result.error_stage = result.stages_run[-1] if result.stages_run else "unknown"
        result.error_message = str(exc)
        result.success = False

        try:
            session.refresh(article)
            result.final_status = article.status
        except Exception:
            pass

        logger.exception("pipeline article_id=%s 异常终止于 %s", article_id, result.error_stage)

    result.total_duration_ms = int((time.monotonic() - start_time) * 1000)
    _write_overview_log(repo, article_id, result)
    logger.info("pipeline article_id=%s: %s", article_id, result.summary())
    return result.success


# ---- 阶段执行函数 ----

def _run_parser(article: Any, session: Any, result: PipelineResult) -> None:
    """执行 parser 阶段。"""
    from pn04.parser import parse_article

    result.stages_run.append("parser")
    parse_article(article, session)
    session.refresh(article)


def _run_cleaner(article_id: int, session: Any, result: PipelineResult) -> None:
    """执行 cleaner 阶段。"""
    from pn05.cleaner import clean_article

    result.stages_run.append("cleaner")
    clean_article(article_id, session)


def _run_refiner(article_id: int, session: Any, result: PipelineResult) -> None:
    """执行 refiner 阶段；该阶段失败不阻塞后续分析。"""
    from pn05.refiner import refine_article

    result.stages_run.append("refiner")
    refine_article(article_id, session)


def _run_rule_engine(article_id: int, session: Any, result: PipelineResult) -> bool:
    """
    执行 rule_engine 阶段。
    Returns: True=需要继续 LLM, False=已入库完成
    """
    from pn06.rule_engine import analyze_article

    result.stages_run.append("rule_engine")
    rule_result = analyze_article(article_id, session)
    return rule_result.need_llm


def _run_llm_infer(article_id: int, session: Any, result: PipelineResult) -> None:
    """执行 llm_infer 阶段。"""
    from pn07.llm_infer import infer_article

    result.stages_run.append("llm_infer")
    infer_article(article_id, session)


# ---- 辅助函数 ----

def _resolve_retry_stage(error_msg: str) -> str | None:
    """根据 error_msg 判断失败阶段，返回应从哪个阶段重试。"""
    msg_lower = error_msg.lower()
    # 按顺序检查：越早的阶段越优先
    for stage in ["parser", "cleaner", "refiner", "rule_engine", "llm_infer"]:
        if stage in msg_lower:
            return stage
    # 无法判断 → 从头开始
    return "parser"


def _write_overview_log(repo: Any, article_id: int, result: PipelineResult) -> None:
    """写流水线总览日志。"""
    try:
        repo.save_task_log(
            article_id=article_id,
            stage="pipeline",
            status="success" if result.success else "failed",
            message=result.summary(),
            duration_ms=result.total_duration_ms,
        )
    except Exception:
        pass
