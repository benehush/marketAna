"""
文章仓库层 - 封装 Article 相关的所有数据库操作
包括：文章 CRUD、文本处理、分析结果存储、状态管理、任务日志、趋势查询等
"""
from datetime import datetime, time
import hashlib
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from back_end.app.core.exceptions import AppException, ErrorCode
from back_end.app.core.review import REVIEW_REASON_CODES
from back_end.app.core.display import displayable_product_clause, formal_analysis_clause
from back_end.app.core.status import ARTICLE_STATUS_VALUES, ArticleProcessingStatus
from back_end.app.models import (
    ANALYSIS_METHOD_VALUES,
    DIRECTION_VALUES,
    AnalysisResult,
    AnalysisReviewQueue,
    Article,
    ArticleProductSegment,
    ArticleText,
    ManualConfirmation,
    TaskLog,
)
from back_end.app.repositories.base import BaseRepository
from data_proccessing.catalog import product_key_for_name


class ArticleRepository(BaseRepository):
    """文章数据仓库，提供文章全生命周期的数据访问方法"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        
    # 向articles表中插入一条新记录
    def create_article(
        self,
        *,
        title: str,
        source: str | None = None,
        company: str | None = None,
        file_url: str | None = None,
        file_type: str | None = None,
        publish_time: datetime | None = None,
    ) -> Article:
        """创建新文章记录。

        Args:
            title:       文章标题
            source:      文章来源
            company:     关联公司名称
            file_url:    上传文件地址
            file_type:   文件类型（如 pdf、docx）
            publish_time:文章发布时间

        Returns:
            创建的 Article 实例
        """
        article = Article(
            title=title,
            source=source,
            company=company,
            file_url=file_url,
            file_type=file_type,
            publish_time=publish_time,
        )
        self.session.add(article)
        self.session.flush()
        return article

    def get_article(self, article_id: int) -> Article | None:
        """根据 ID 查询单篇文章（不含关联数据）。"""
        return self.session.scalar(select(Article).where(Article.id == article_id))

    def get_article_detail(self, article_id: int) -> Article | None:
        """根据 ID 查询文章详情，同时加载关联的文本、分析结果、任务日志、人工确认记录。"""
        return self.session.scalar(
            select(Article)
            .options(
                selectinload(Article.text),
                selectinload(Article.analysis_results),
                selectinload(Article.product_segments),
                selectinload(Article.task_logs),
                selectinload(Article.manual_confirmations),
                selectinload(Article.review_queue),
            )
            .where(Article.id == article_id)
        )

    def require_article(self, article_id: int) -> Article:
        """根据 ID 查找文章，不存在则抛出 404 异常。"""
        article = self.get_article(article_id)
        if article is None:
            raise AppException(
                code=ErrorCode.NOT_FOUND,
                message="Article not found",
                detail={"article_id": article_id},
                status_code=404,
            )
        return article

    def get_pending_articles(self, limit: int, *, lock: bool = False) -> list[Article]:
        """获取待处理的文章队列。

        Args:
            limit: 最大获取数量
            lock:  是否对选中记录加锁（防止并发重复处理）
                   仅在支持行级锁的数据库（MySQL/PostgreSQL）中生效

        Returns:
            待处理的 Article 列表，按创建时间升序排列
        """
        stmt = (
            select(Article)
            .where(Article.status == ArticleProcessingStatus.PENDING.value)
            .order_by(Article.created_at.asc(), Article.id.asc())
            .limit(limit)
        )
        if lock and self._supports_skip_locked():
            stmt = stmt.with_for_update(skip_locked=True)
        return list(self.session.scalars(stmt).all())

    def save_raw_text(
        self,
        article_id: int,
        raw_text: str,
        *,
        parser_type: str | None = None,
    ) -> ArticleText:
        """保存从文件提取的原始文本。

        Args:
            article_id:  文章 ID
            raw_text:    原始文本内容
            parser_type: 文本解析器类型

        Returns:
            更新后的 ArticleText 实例
        """
        self.require_article(article_id)
        article_text = self._get_or_create_article_text(article_id)
        article_text.raw_text = raw_text
        article_text.raw_length = len(raw_text)
        article_text.parser_type = parser_type
        self.update_status(article_id, ArticleProcessingStatus.PARSED)
        self.session.flush()
        return article_text

    def save_cleaned_text(self, article_id: int, cleaned_text: str) -> ArticleText:
        """保存清洗后的文本。

        Args:
            article_id:   文章 ID
            cleaned_text: 清洗后的文本内容

        Returns:
            更新后的 ArticleText 实例
        """
        self.require_article(article_id)
        article_text = self._get_or_create_article_text(article_id)
        article_text.cleaned_text = cleaned_text
        article_text.cleaned_length = len(cleaned_text)
        self.update_status(article_id, ArticleProcessingStatus.CLEANED)
        self.session.flush()
        return article_text

    def save_refined_text(self, article_id: int, refined_text: str) -> ArticleText:
        """保存 LLM 精修后的用户展示文本，不改变文章处理状态。"""
        self.require_article(article_id)
        article_text = self._get_or_create_article_text(article_id)
        article_text.refined_text = refined_text
        article_text.refined_length = len(refined_text)
        self.session.flush()
        return article_text

    def save_product_segments(
        self,
        article_id: int,
        segments: list[dict[str, Any]],
    ) -> list[ArticleProductSegment]:
        """保存按品种切分的正文片段；每次重跑替换该文章旧分段。"""
        article = self.require_article(article_id)
        existing = list(
            self.session.scalars(
                select(ArticleProductSegment).where(ArticleProductSegment.article_id == article_id)
            ).all()
        )
        for segment in existing:
            self.session.delete(segment)
        self.session.flush()

        saved: list[ArticleProductSegment] = []
        for index, item in enumerate(segments):
            product = str(item.get("product") or "未知").strip() or "未知"
            contract = item.get("contract")
            contract = str(contract).strip() if contract is not None and str(contract).strip() else None
            cleaned_text = str(item.get("cleaned_text") or "").strip()
            refined_text_value = item.get("refined_text")
            refined_text = (
                str(refined_text_value).strip()
                if refined_text_value is not None and str(refined_text_value).strip()
                else None
            )
            segment = ArticleProductSegment(
                article_id=article_id,
                product=product,
                product_key=str(item.get("product_key") or product_key_for_name(product) or _legacy_product_key(product)),
                raw_product_name=(
                    str(item.get("raw_product_name")).strip()
                    if item.get("raw_product_name") else None
                ),
                resolution_method=str(item.get("resolution_method") or "unknown"),
                resolution_confidence=float(item.get("resolution_confidence") or item.get("confidence") or 0.0),
                contract=contract,
                contract_key=self._normalize_contract_key(contract),
                segment_index=int(item.get("segment_index", index) or 0),
                section_type=str(item.get("section_type") or "core").strip() or "core",
                heading=(str(item.get("heading")).strip() if item.get("heading") else None),
                cleaned_text=cleaned_text,
                refined_text=refined_text,
                cleaned_length=len(cleaned_text),
                refined_length=len(refined_text or ""),
                start_char=item.get("start_char"),
                end_char=item.get("end_char"),
                confidence=float(item.get("confidence") or 0.0),
            )
            self.session.add(segment)
            saved.append(segment)

        self.session.flush()
        self.session.expire(article, ["product_segments"])
        return saved

    def get_product_segments(self, article_id: int) -> list[ArticleProductSegment]:
        """读取一篇文章的品种分段，按原文顺序排序。"""
        return list(
            self.session.scalars(
                select(ArticleProductSegment)
                .where(ArticleProductSegment.article_id == article_id)
                .order_by(
                    ArticleProductSegment.segment_index.asc(),
                    ArticleProductSegment.id.asc(),
                )
            ).all()
        )

    def find_product_segment(
        self,
        article_id: int,
        product: str,
        contract_key: str | None = None,
    ) -> ArticleProductSegment | None:
        """查找最适合某个分析结果的品种正文片段。"""
        product = (product or "").strip()
        if not product:
            return None
        segments = self.get_product_segments(article_id)
        displayable = [
            segment
            for segment in segments
            if segment.product == product and segment.section_type != "unknown"
        ]
        normalized_contract = self._normalize_contract_key(contract_key)
        if normalized_contract:
            exact = [segment for segment in displayable if segment.contract_key == normalized_contract]
            if exact:
                displayable = exact
        if not displayable:
            return None

        section_priority = {"core": 0, "ocr": 1, "ai": 2, "table": 3, "mixed": 4}
        return sorted(
            displayable,
            key=lambda item: (
                section_priority.get(item.section_type, 9),
                -float(item.confidence or 0.0),
                item.segment_index,
                item.id or 0,
            ),
        )[0]

    def save_analysis_result(
        self,
        article_id: int,
        *,
        product: str,
        product_key: str | None = None,
        direction: str,
        reason: str | None,
        confidence: float,
        analysis_method: str,
        need_manual_review: bool = False,
        analysis_time: datetime | None = None,
        mark_stored: bool = True,
        contract: str | None = None,
        is_primary: bool | None = None,
        model_name: str | None = None,
        llm_duration_ms: int | None = None,
        llm_retry_count: int | None = None,
        llm_error_msg: str | None = None,
    ) -> AnalysisResult:
        """保存单条分析结果，兼容旧调用方。"""
        results = self.save_analysis_results(
            article_id,
            [
                {
                    "product": product,
                    "product_key": product_key or product_key_for_name(product) or _legacy_product_key(product),
                    "contract": contract,
                    "direction": direction,
                    "reason": reason,
                    "confidence": confidence,
                    "analysis_method": analysis_method,
                    "need_manual_review": need_manual_review,
                    "analysis_time": analysis_time,
                    "is_primary": is_primary,
                    "model_name": model_name,
                    "llm_duration_ms": llm_duration_ms,
                    "llm_retry_count": llm_retry_count,
                    "llm_error_msg": llm_error_msg,
                }
            ],
            mark_stored=mark_stored,
        )
        return results[0]

    def save_analysis_results(
        self,
        article_id: int,
        results: list[dict[str, Any]],
        *,
        mark_stored: bool = True,
    ) -> list[AnalysisResult]:
        """批量保存一篇文章的多品种分析结果。

        按 (article_id, product_key, contract_key) 幂等更新；不删除未出现在本批次
        的既有结果，便于规则高置信结果和 LLM 补全结果分阶段合并。
        """
        self.require_article(article_id)
        if not results:
            return []

        normalized: list[dict[str, Any]] = []
        for item in results:
            product = str(item.get("product") or "").strip()
            direction = str(item.get("direction") or "").strip()
            confidence = float(item.get("confidence") or 0.0)
            analysis_method = str(item.get("analysis_method") or "").strip()
            if not product:
                raise AppException(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Invalid product",
                    detail={"product": product},
                )
            self._validate_direction(direction)
            self._validate_confidence(confidence)
            self._validate_analysis_method(analysis_method)
            contract = item.get("contract")
            contract = str(contract).strip() if contract is not None and str(contract).strip() else None
            normalized.append(
                {
                    **item,
                    "product": product,
                    "product_key": str(item.get("product_key") or product_key_for_name(product) or _legacy_product_key(product)),
                    "contract": contract,
                    "contract_key": self._normalize_contract_key(item.get("contract_key") or contract),
                    "direction": direction,
                    "confidence": confidence,
                    "analysis_method": analysis_method,
                }
            )

        explicit_primary = any(item.get("is_primary") is True for item in normalized)
        if not explicit_primary:
            best = max(normalized, key=lambda item: item["confidence"])
            best["is_primary"] = True

        if any(item.get("is_primary") is True for item in normalized):
            existing_results = list(self.session.scalars(
                select(AnalysisResult).where(AnalysisResult.article_id == article_id)
            ).all())
            manual_primary = any(
                existing.analysis_method == "manual" and existing.is_primary
                for existing in existing_results
            )
            incoming_manual = any(item["analysis_method"] == "manual" for item in normalized)
            if manual_primary and not incoming_manual:
                for item in normalized:
                    item["is_primary"] = False
            else:
                for existing in existing_results:
                    existing.is_primary = False

        saved: list[AnalysisResult] = []
        for item in normalized:
            result = self.session.scalar(
                select(AnalysisResult).where(
                    AnalysisResult.article_id == article_id,
                    AnalysisResult.product_key == item["product_key"],
                    AnalysisResult.contract_key == item["contract_key"],
                )
            )
            if result is None:
                result = AnalysisResult(article_id=article_id)
                self.session.add(result)
            elif result.analysis_method == "manual" and item["analysis_method"] != "manual":
                saved.append(result)
                continue

            result.product = item["product"]
            result.product_key = item["product_key"]
            result.contract = item["contract"]
            result.contract_key = item["contract_key"]
            result.direction = item["direction"]
            result.reason = item.get("reason")
            result.confidence = item["confidence"]
            result.analysis_method = item["analysis_method"]
            result.need_manual_review = bool(item.get("need_manual_review", False))
            result.evidence_json = item.get("evidence")
            result.is_primary = bool(item.get("is_primary", False))
            result.model_name = item.get("model_name")
            result.llm_duration_ms = item.get("llm_duration_ms")
            result.llm_retry_count = item.get("llm_retry_count")
            result.llm_error_msg = item.get("llm_error_msg")
            if item.get("analysis_time") is not None:
                result.analysis_time = item["analysis_time"]
            saved.append(result)

        if mark_stored:
            self.update_status(article_id, ArticleProcessingStatus.STORED)
        self.session.flush()
        return saved

    def update_status(
        self,
        article_id: int,
        status: ArticleProcessingStatus | int,
        *,
        error_msg: str | None = None,
    ) -> Article:
        """更新文章处理状态。

        Args:
            article_id: 文章 ID
            status:     目标状态（ArticleProcessingStatus 枚举或整数值）
            error_msg:  失败时的错误信息（仅在 status == FAILED 时写入）

        Returns:
            更新后的 Article 实例
        """
        article = self.require_article(article_id)
        status_value = int(status)
        if status_value not in ARTICLE_STATUS_VALUES:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid article status",
                detail={"status": status_value},
            )
        article.status = status_value
        article.error_msg = error_msg if status_value == ArticleProcessingStatus.FAILED else None
        self.session.flush()
        return article

    def mark_failed(
        self,
        article_id: int,
        *,
        stage: str,
        message: str,
        duration_ms: int | None = None,
    ) -> Article:
        """将文章标记为失败状态，并记录任务日志。

        Args:
            article_id:  文章 ID
            stage:       失败阶段
            message:     失败原因描述
            duration_ms: 耗时（毫秒）

        Returns:
            更新后的 Article 实例
        """
        article = self.update_status(
            article_id,
            ArticleProcessingStatus.FAILED,
            error_msg=message,
        )
        self.save_task_log(
            article_id=article_id,
            stage=stage,
            status="failed",
            message=message,
            duration_ms=duration_ms,
        )
        self.session.flush()
        return article

    def save_task_log(
        self,
        *,
        article_id: int | None,
        stage: str,
        status: str,
        message: str | None = None,
        duration_ms: int | None = None,
    ) -> TaskLog:
        """记录任务执行日志。

        Args:
            article_id:  关联的文章 ID（允许为 None，用于全局任务）
            stage:       任务阶段
            status:      状态（如 success / failed）
            message:     日志消息
            duration_ms: 耗时（毫秒）

        Returns:
            创建的 TaskLog 实例
        """
        if article_id is not None:
            self.require_article(article_id)
        log = TaskLog(
            article_id=article_id,
            stage=stage,
            status=status,
            message=message,
            duration_ms=duration_ms,
        )
        self.session.add(log)
        self.session.flush()
        return log

    def list_articles(
        self,
        *,
        product: str | None = None,
        product_key: str | None = None,
        company: str | None = None,
        direction: str | None = None,
        status: int | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Article], int]:
        """分页查询文章列表，支持多字段组合筛选。

        Args:
            product:    产品名称筛选
            company:    公司名称筛选
            direction:  市场方向筛选
            status:     文章状态筛选
            start_time: 发布时间范围（起始）
            end_time:   发布时间范围（截止）
            keyword:    关键词模糊搜索（匹配标题、来源、公司、分析原因）
            page:       页码（从 1 开始）
            page_size:  每页条数

        Returns:
            (文章列表, 总记录数)
        """
        stmt = self._article_filter_stmt(
            product=product,
            product_key=product_key,
            company=company,
            direction=direction,
            status=status,
            start_time=start_time,
            end_time=end_time,
            keyword=keyword,
        )
        total_stmt = stmt.with_only_columns(func.count(Article.id)).order_by(None)
        total = int(self.session.scalar(total_stmt) or 0)
        items = list(
            self.session.scalars(
                stmt.options(
                    selectinload(Article.analysis_results),
                    selectinload(Article.text),
                )
                .order_by(
                    Article.publish_time.is_(None),
                    Article.publish_time.desc(),
                    Article.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return items, total

    def get_dashboard_summary(self, *, today: datetime | None = None) -> dict[str, Any]:
        """获取仪表盘概览统计数据。

        Args:
            today: 指定作为"今天"的日期（用于测试时注入），默认为当前时间

        Returns:
            dict 包含：
            - today_articles:         今日新增文章数
            - total_articles:         文章总数
            - success_count:          处理成功数
            - failed_count:           处理失败数
            - success_rate:           成功率
            - manual_review_count:    待人工复核数
            - direction_distribution: 各方向的预测分布
        """
        resolved_today = (today or datetime.now()).date()
        start = datetime.combine(resolved_today, time.min)
        end = datetime.combine(resolved_today, time.max)

        # 今日新增文章数
        today_count = int(
            self.session.scalar(
                select(func.count(Article.id)).where(
                    Article.created_at >= start,
                    Article.created_at <= end,
                )
            )
            or 0
        )
        # 成功存储数
        success_count = int(
            self.session.scalar(
                select(func.count(Article.id)).where(Article.status == ArticleProcessingStatus.STORED.value)
            )
            or 0
        )
        # 失败数
        failed_count = int(
            self.session.scalar(
                select(func.count(Article.id)).where(Article.status == ArticleProcessingStatus.FAILED.value)
            )
            or 0
        )
        # 文章总数
        total_count = int(self.session.scalar(select(func.count(Article.id))) or 0)
        # 待人工复核数
        result_review_count = int(
            self.session.scalar(
                select(func.count(AnalysisResult.id))
                .join(Article, Article.id == AnalysisResult.article_id)
                .where(
                    Article.status == ArticleProcessingStatus.STORED.value,
                    AnalysisResult.need_manual_review.is_(True),
                    displayable_product_clause(AnalysisResult.product),
                )
            )
            or 0
        )
        queue_review_count = int(
            self.session.scalar(
                select(func.count(AnalysisReviewQueue.id))
                .join(Article, Article.id == AnalysisReviewQueue.article_id)
                .where(
                    Article.status == ArticleProcessingStatus.STORED.value,
                    AnalysisReviewQueue.status == "pending",
                )
            )
            or 0
        )
        manual_review_count = result_review_count + queue_review_count
        # 方向分布统计
        direction_rows = self.session.execute(
            select(AnalysisResult.direction, func.count(AnalysisResult.id))
            .join(Article, Article.id == AnalysisResult.article_id)
            .where(
                Article.status == ArticleProcessingStatus.STORED.value,
                formal_analysis_clause(AnalysisResult),
            )
            .group_by(AnalysisResult.direction)
        ).all()
        direction_distribution = {direction: 0 for direction in DIRECTION_VALUES}
        direction_distribution.update({row[0]: int(row[1]) for row in direction_rows})

        return {
            "today_articles": today_count,
            "total_articles": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "success_rate": success_count / total_count if total_count else 0,
            "manual_review_count": manual_review_count,
            "direction_distribution": direction_distribution,
        }

    def get_trends(
        self,
        *,
        product: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取趋势分析数据，按日期、产品、方向分组统计预测数量。

        Args:
            product:    筛选特定产品
            start_time: 统计起始时间
            end_time:   统计截止时间

        Returns:
            列表，每项包含 date、product、direction、count 字段
        """
        # 日期取文章发布时间和分析时间的非空值
        trend_date = func.date(func.coalesce(Article.publish_time, AnalysisResult.analysis_time))
        stmt = (
            select(
                trend_date.label("date"),
                AnalysisResult.product,
                AnalysisResult.direction,
                func.count(AnalysisResult.id).label("count"),
            )
            .join(Article, Article.id == AnalysisResult.article_id)
            .where(
                Article.status == ArticleProcessingStatus.STORED.value,
                formal_analysis_clause(AnalysisResult),
            )
            .group_by("date", AnalysisResult.product, AnalysisResult.direction)
            .order_by("date", AnalysisResult.product)
        )
        if product:
            stmt = stmt.where(AnalysisResult.product == product)
        if start_time is not None:
            stmt = stmt.where(func.coalesce(Article.publish_time, AnalysisResult.analysis_time) >= start_time)
        if end_time is not None:
            stmt = stmt.where(func.coalesce(Article.publish_time, AnalysisResult.analysis_time) <= end_time)

        return [
            {
                "date": str(row.date),
                "product": row.product,
                "direction": row.direction,
                "count": int(row.count),
            }
            for row in self.session.execute(stmt).all()
        ]

    def confirm_result(
        self,
        result_id: int,
        *,
        product: str,
        product_key: str | None = None,
        direction: str,
        reason: str | None,
        confidence: float,
        confirmed_by: str | None = None,
        note: str | None = None,
    ) -> ManualConfirmation:
        """人工确认并修正分析结果。

        创建一条修正记录（ManualConfirmation），同时更新原分析结果的数据，
        并将文章状态置为 STORED。

        Args:
            result_id:     原分析结果 ID
            product:       确认后的产品名称
            direction:     确认后的方向
            reason:        确认后的原因
            confidence:    确认后的置信度
            confirmed_by:  确认人
            note:          备注说明

        Returns:
            创建的 ManualConfirmation 实例
        """
        self._validate_direction(direction)
        self._validate_confidence(confidence)
        result = self.session.scalar(
            select(AnalysisResult).where(AnalysisResult.id == result_id)
        )
        if result is None:
            raise AppException(
                code=ErrorCode.NOT_FOUND,
                message="Analysis result not found",
                detail={"result_id": result_id},
                status_code=404,
            )

        # 保存原始数据与修正后数据的对比记录
        confirmation = ManualConfirmation(
            article_id=result.article_id,
            original_product=result.product,
            original_product_key=result.product_key,
            original_direction=result.direction,
            original_reason=result.reason,
            original_confidence=result.confidence,
            confirmed_product=product,
            confirmed_product_key=product_key or product_key_for_name(product) or None,
            confirmed_direction=direction,
            confirmed_reason=reason,
            confirmed_confidence=confidence,
            confirmed_by=confirmed_by,
            note=note,
        )
        self.session.add(confirmation)

        # 用修正数据覆盖原分析结果
        result.product = product
        result.product_key = product_key or product_key_for_name(product) or _legacy_product_key(product)
        result.contract_key = self._normalize_contract_key(result.contract)
        result.direction = direction
        result.reason = reason
        result.confidence = confidence
        result.analysis_method = "manual"
        result.need_manual_review = False
        self.update_status(result.article_id, ArticleProcessingStatus.STORED)
        self.session.flush()
        return confirmation

    def reject_review_item(
        self,
        review_id: int,
        *,
        reviewed_by: str,
        reason_code: str,
        note: str | None = None,
    ) -> AnalysisReviewQueue:
        """Persist a false-positive decision; pipeline imports must not reopen it."""
        reviewed_by = reviewed_by.strip()
        if not reviewed_by or reason_code not in REVIEW_REASON_CODES:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="A reviewer and valid rejection reason are required",
                detail={"reason_code": reason_code},
            )
        item = self.session.scalar(
            select(AnalysisReviewQueue).where(AnalysisReviewQueue.id == review_id)
        )
        if item is None:
            raise AppException(
                code=ErrorCode.NOT_FOUND,
                message="Review item not found",
                detail={"review_id": review_id},
                status_code=404,
            )
        if item.status == "resolved":
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Resolved review item cannot be rejected",
                detail={"review_id": review_id},
            )
        item.status = "rejected"
        item.reviewed_by = reviewed_by
        item.review_reason_code = reason_code
        item.review_note = note
        item.reviewed_at = datetime.now()
        self.session.flush()
        return item

    def create_manual_conclusion(
        self,
        review_id: int,
        *,
        direction: str,
        reason: str,
        evidence: str,
        product_key: str,
        reviewed_by: str,
    ) -> AnalysisResult:
        """Create a formal result only from a complete, pending manual decision."""
        direction = direction.strip()
        reason = reason.strip()
        evidence = evidence.strip()
        self._validate_direction(direction)
        if not reason or not evidence:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Direction, reason and evidence are required",
                detail={"review_id": review_id},
            )
        reviewed_by = reviewed_by.strip()
        if not reviewed_by:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Reviewer is required",
            )
        item = self.session.scalar(
            select(AnalysisReviewQueue).where(AnalysisReviewQueue.id == review_id)
        )
        if item is None:
            raise AppException(
                code=ErrorCode.NOT_FOUND,
                message="Review item not found",
                detail={"review_id": review_id},
                status_code=404,
            )
        if item.status != "pending":
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Only pending review items can create a conclusion",
                detail={"review_id": review_id, "status": item.status},
            )
        from data_proccessing.catalog import get_product

        catalog_product = get_product(product_key.strip())
        if catalog_product is None or not catalog_product.active or catalog_product.product_key.startswith("GROUP."):
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="A valid active product is required for a formal conclusion",
                detail={"review_id": review_id, "product_key": product_key},
            )
        confirmed_product = catalog_product.display_name
        confirmed_key = catalog_product.product_key
        result = self.save_analysis_result(
            item.article_id,
            product=confirmed_product,
            product_key=confirmed_key or None,
            direction=direction,
            reason=reason,
            confidence=1.0,
            analysis_method="manual",
            need_manual_review=False,
            mark_stored=True,
            is_primary=True,
        )
        result.evidence_json = {
            "summary": reason,
            "source": "manual",
            "excerpts": [{"quote": evidence, "source": "manual", "start_char": None, "end_char": None, "match_type": "manual"}],
            "notes": "人工审核人员填写的正式结论证据",
        }
        self.session.add(ManualConfirmation(
            article_id=item.article_id,
            original_product=item.product,
            original_product_key=item.product_key,
            original_direction=None,
            original_reason=item.reason,
            original_confidence=None,
            confirmed_product=confirmed_product,
            confirmed_product_key=result.product_key,
            confirmed_direction=direction,
            confirmed_reason=reason,
            confirmed_confidence=1.0,
            confirmed_by=reviewed_by,
            note=f"由人工审核项 #{review_id} 创建",
        ))
        item.status = "resolved"
        item.reviewed_by = reviewed_by
        item.review_note = reason
        item.reviewed_at = datetime.now()
        self.session.flush()
        return result

    # ==================== 私有辅助方法 ====================

    def _get_or_create_article_text(self, article_id: int) -> ArticleText:
        """获取或创建文章对应的 ArticleText 记录。"""
        article_text = self.session.scalar(
            select(ArticleText).where(ArticleText.article_id == article_id)
        )
        if article_text is None:
            article_text = ArticleText(article_id=article_id)
            self.session.add(article_text)
            self.session.flush()
        return article_text

    def _article_filter_stmt(
        self,
        *,
        product: str | None,
        product_key: str | None,
        company: str | None,
        direction: str | None,
        status: int | None,
        start_time: datetime | None,
        end_time: datetime | None,
        keyword: str | None,
    ) -> Select[tuple[Article]]:
        """构建文章列表的筛选查询语句。

        使用 relationship.any 过滤分析结果，避免一文多结果导致文章重复。
        """
        displayable_clause = displayable_product_clause(AnalysisResult.product)
        # Article list is also the processing inbox: a successfully parsed
        # article with no formal result must remain visible for review.
        stmt = select(Article).where(
            or_(
                ~Article.analysis_results.any(),
                Article.analysis_results.any(displayable_clause),
            )
        )
        if product:
            stmt = stmt.where(
                Article.analysis_results.any(
                    and_(
                        displayable_clause,
                        AnalysisResult.product == product,
                    )
                )
            )
        if product_key:
            stmt = stmt.where(
                Article.analysis_results.any(
                    and_(
                        displayable_clause,
                        AnalysisResult.product_key == product_key,
                    )
                )
            )
        if company:
            stmt = stmt.where(Article.company == company)
        if direction:
            self._validate_direction(direction)
            stmt = stmt.where(
                Article.analysis_results.any(
                    and_(
                        displayable_clause,
                        AnalysisResult.direction == direction,
                    )
                )
            )
        if status is not None:
            if status not in ARTICLE_STATUS_VALUES:
                raise AppException(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Invalid article status",
                    detail={"status": status},
                )
            stmt = stmt.where(Article.status == status)
        if start_time is not None:
            stmt = stmt.where(Article.publish_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(Article.publish_time <= end_time)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    Article.title.like(pattern),
                    Article.source.like(pattern),
                    Article.company.like(pattern),
                    Article.analysis_results.any(
                        and_(
                            displayable_clause,
                            AnalysisResult.reason.like(pattern),
                        )
                    ),
                )
            )
        return stmt

    def _supports_skip_locked(self) -> bool:
        """检测当前数据库是否支持 SKIP LOCKED 语法。

        仅 MySQL 和 PostgreSQL 支持该特性，SQLite 不支持。
        """
        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        return dialect_name in {"mysql", "postgresql"}

    @staticmethod
    def _validate_direction(direction: str) -> None:
        """校验市场方向值是否在允许列表中。"""
        if direction not in DIRECTION_VALUES:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid direction",
                detail={"direction": direction, "allowed": DIRECTION_VALUES},
            )

    @staticmethod
    def _validate_analysis_method(analysis_method: str) -> None:
        """校验分析方法值是否在允许列表中。"""
        if analysis_method not in ANALYSIS_METHOD_VALUES:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid analysis method",
                detail={"analysis_method": analysis_method, "allowed": ANALYSIS_METHOD_VALUES},
            )

    @staticmethod
    def _validate_confidence(confidence: float) -> None:
        """校验置信度是否在 0 ~ 1 范围内。"""
        if confidence < 0 or confidence > 1:
            raise AppException(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid confidence",
                detail={"confidence": confidence},
            )

    @staticmethod
    def _normalize_contract_key(contract: str | None) -> str:
        """归一化合约键，空合约使用空字符串参与唯一约束。"""
        if not contract:
            return ""
        return str(contract).strip().lower().replace("合约", "").replace(" ", "")


def _legacy_product_key(product: str) -> str:
    """Give legacy/manual callers a stable non-empty identity."""
    normalized = " ".join((product or "").strip().split())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"LEGACY.{digest}"
