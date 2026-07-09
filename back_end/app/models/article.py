"""
数据库模型定义 - 文章及关联数据的 ORM 映射

包含以下模型：
- Article:           文章主表
- ArticleText:       文章文本内容（原始/清洗后）
- AnalysisResult:    LLM 或人工分析结果
- TaskLog:           任务执行日志
- ManualConfirmation:人工修正记录
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from back_end.app.core.database import Base
from back_end.app.core.status import ARTICLE_STATUS_VALUES, ArticleProcessingStatus


# MySQL 环境下使用 LONGTEXT 以支持超长文本，其他数据库回退到普通 Text
TEXT_BODY = Text().with_variant(LONGTEXT, "mysql")

# 允许的市场方向枚举值
DIRECTION_VALUES = ("看涨", "看跌", "中性")

# 允许的分析方法枚举值：规则 / LLM / 人工
ANALYSIS_METHOD_VALUES = ("rule", "llm", "manual")


class Article(Base):
    """文章主表 - 存储从外部导入的原始文章元信息。"""
    __tablename__ = "articles"
    # 额外规则
    __table_args__ = (
        # 状态字段的值必须在定义的合法范围内
        CheckConstraint(
            f"status in {ARTICLE_STATUS_VALUES}",
            name="ck_articles_status",
        ),
        # 按状态 + 创建时间快速检索待处理文章
        Index("ix_articles_status_created_at", "status", "created_at"),
        Index("ix_articles_company", "company"),
        Index("ix_articles_publish_time", "publish_time"),
    )
    # 普通字段映射成表字段
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)        # 文章标题
    source: Mapped[str | None] = mapped_column(String(128), nullable=True) # 文章来源
    company: Mapped[str | None] = mapped_column(String(128), nullable=True) # 关联公司
    file_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 上传文件地址
    file_type: Mapped[str | None] = mapped_column(String(32), nullable=True)   # 文件类型（pdf/docx 等）
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 原文发布时间
    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=ArticleProcessingStatus.PENDING.value,  # 默认等待处理
        index=True,
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)  # 处理失败时的错误信息
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),  # 插入时自动设为当前时间
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),  # 更新时自动设为当前时间
    )

    # 关联关系
    text: Mapped[Optional["ArticleText"]] = relationship(
        back_populates="article",      # 关联 ArticleText 的 article 属性
        cascade="all, delete-orphan",  # 级联删除，删除文章时同时删除关联的文本记录
        uselist=False,                 # 一对一
    )
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )
    task_logs: Mapped[list["TaskLog"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",  # 一对多
    )
    manual_confirmations: Mapped[list["ManualConfirmation"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )

    @property
    def analysis_result(self) -> Optional["AnalysisResult"]:
        """Backward-compatible primary analysis result."""
        if not self.analysis_results:
            return None
        primary = [result for result in self.analysis_results if result.is_primary]
        if primary:
            return sorted(primary, key=lambda item: item.id or 0)[0]
        return sorted(
            self.analysis_results,
            key=lambda item: (item.confidence or 0.0, -(item.id or 0)),
            reverse=True,
        )[0]


class ArticleText(Base):
    """文章文本内容表 - 保存文件的原始、清洗和精修文本。"""
    __tablename__ = "article_texts"
    __table_args__ = (
        # 一篇文章只能对应一条文本记录
        UniqueConstraint("article_id", name="uq_article_texts_article_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_text: Mapped[str | None] = mapped_column(TEXT_BODY, nullable=True)      # 原始提取文本
    cleaned_text: Mapped[str | None] = mapped_column(TEXT_BODY, nullable=True)  # 清洗后的文本
    refined_text: Mapped[str | None] = mapped_column(TEXT_BODY, nullable=True)  # LLM 精修后的展示文本
    raw_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)    # 原始文本长度
    cleaned_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0) # 清洗后文本长度
    refined_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0) # 精修后文本长度
    parser_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 使用的解析器类型
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # 关联Article表的text属性，建立一对一关系
    article: Mapped[Article] = relationship(back_populates="text")


class AnalysisResult(Base):
    """分析结果表 - 存储 LLM 或规则引擎对文章的市场分析结论。"""
    __tablename__ = "analysis_results"
    __table_args__ = (
        # 一篇文章可对应多个品种/合约结果，同一品种合约保持当前有效结果唯一
        UniqueConstraint("article_id", "product", "contract_key", name="uq_analysis_results_article_product_contract"),
        # 方向字段必须在合法枚举值内
        CheckConstraint(
            f"direction in {DIRECTION_VALUES}",
            name="ck_analysis_results_direction",
        ),
        # 置信度必须在 0 ~ 1 之间
        CheckConstraint(
            "confidence >= 0 and confidence <= 1",
            name="ck_analysis_results_confidence",
        ),
        # 分析方法必须在合法枚举值内
        CheckConstraint(
            f"analysis_method in {ANALYSIS_METHOD_VALUES}",
            name="ck_analysis_results_method",
        ),
        # 常用查询索引
        Index("ix_analysis_results_product", "product"),
        Index("ix_analysis_results_direction", "direction"),
        Index("ix_analysis_results_product_direction", "product", "direction"),
        Index("ix_analysis_results_analysis_time", "analysis_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product: Mapped[str] = mapped_column(String(128), nullable=False)       # 关联产品名称
    contract: Mapped[str | None] = mapped_column(String(64), nullable=True) # 合约，如 05、2505
    contract_key: Mapped[str] = mapped_column(String(64), nullable=False, default="") # 合约归一化键
    direction: Mapped[str] = mapped_column(String(16), nullable=False)      # 市场方向：看涨/看跌/中性
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)         # 分析理由
    confidence: Mapped[float] = mapped_column(Float, nullable=False)        # 置信度（0~1）
    analysis_method: Mapped[str] = mapped_column(String(32), nullable=False) # 分析方法（rule/llm/manual）
    need_manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否需要人工复核
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否为文章主结果
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),  # 分析完成时间
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # 关联Article表的analysis_result属性，建立一对一关系
    article: Mapped[Article] = relationship(back_populates="analysis_results")


class TaskLog(Base):
    """任务日志表 - 记录每个处理阶段（解析/清洗/分析）的执行情况。"""
    __tablename__ = "task_logs"
    __table_args__ = (
        # 按文章 ID 和阶段快速检索
        Index("ix_task_logs_article_stage", "article_id", "stage"),
        Index("ix_task_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=True,   # 允许为 None，用于记录全局任务
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)          # 任务阶段
    status: Mapped[str] = mapped_column(String(32), nullable=False)         # 状态：success / failed
    message: Mapped[str | None] = mapped_column(Text, nullable=True)        # 日志消息
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True) # 耗时（毫秒）
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    # 关联Article表的task_logs属性，建立一对多关系
    article: Mapped[Article | None] = relationship(back_populates="task_logs")


class ManualConfirmation(Base):
    """人工确认记录表 - 保存人工修正分析结果的完整记录（修改前后对比）。"""
    __tablename__ = "manual_confirmations"
    # 数据的完整性约束，索引来帮助快速查询
    __table_args__ = (
        # 修正后的方向必须在合法枚举值内
        CheckConstraint(
            f"confirmed_direction in {DIRECTION_VALUES}",
            name="ck_manual_confirmations_direction",
        ),
        # 修正后的置信度必须在 0 ~ 1 之间
        CheckConstraint(
            "confirmed_confidence >= 0 and confirmed_confidence <= 1",
            name="ck_manual_confirmations_confidence",
        ),
        Index("ix_manual_confirmations_confirmed_at", "confirmed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 原始值（LLM 自动分析的结果）
    original_product: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 人工修正后的值
    confirmed_product: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmed_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 确认人
    note: Mapped[str | None] = mapped_column(Text, nullable=True)                # 备注
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),  # 确认时间
    )
    # 关联Article表的manual_confirmations属性，建立一对多关系
    article: Mapped[Article] = relationship(back_populates="manual_confirmations")
