"""
pn05 主清洗器

协调各个规范化器和噪声过滤器，提供统一的 clean_article() 入口。
从 article_texts 读取 raw_text，清洗后通过 ArticleRepository 写入 cleaned_text。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from pn05.models import CleanConfig, CleanResult
from pn05.structured_cleaner import clean_text

logger = logging.getLogger(__name__)

__all__ = ["clean_article", "CleanConfig"]


def clean_article(
    article_id: int,
    session: Any,
    *,
    config: CleanConfig | None = None,
) -> str:
    """
    清洗单篇文章的 raw_text，写入 cleaned_text。

    流程:
    1. 从 article_texts 读取 raw_text
    2. 编码检测与修复
    3. HTML 残留移除
    4. 噪声行过滤（关键词 + 正则段落）
    5. 低密度块过滤（页眉/页脚）
    6. 空白规范化 + 全半角转换
    7. 写入 cleaned_text，更新 status=2 + task_log

    Args:
        article_id: 文章 ID
        session: SQLAlchemy Session
        config: 清洗配置

    Returns:
        str: 清洗后的 cleaned_text

    Raises:
        ValueError: raw_text 为空或清洗后为空
    """
    from back_end.app.repositories.articles import ArticleRepository

    config = config or CleanConfig()
    repo = ArticleRepository(session)
    start_time = time.monotonic()

    # 1. 读取 raw_text
    article = repo.get_article_detail(article_id)
    if article is None or article.text is None:
        raise _handle_failure(repo, article_id, "raw_text 不存在")

    raw_text = article.text.raw_text or ""
    if not raw_text.strip():
        raise _handle_failure(repo, article_id, "raw_text 为空")

    raw_length = len(raw_text)
    result = CleanResult(raw_length=raw_length)

    try:
        # 2-7. 编码修复、模板分区、噪声过滤、数字图表噪声压制、格式化输出
        text, clean_stats = clean_text(raw_text, config)
        result.noise_lines_removed = clean_stats.noise_lines_removed
        result.numeric_blocks_removed = clean_stats.numeric_blocks_removed
        result.low_density_removed = clean_stats.low_density_removed

        cleaned_length = len(text)
        result.cleaned_length = cleaned_length

        # 清洗比例检查
        if raw_length > 0:
            result.removal_ratio = (raw_length - cleaned_length) / raw_length
            if result.removal_ratio < 0.05:
                logger.warning("article_id=%s: 几乎无清洗效果 (ratio=%.3f)", article_id, result.removal_ratio)
            elif result.removal_ratio > 0.95:
                logger.warning("article_id=%s: 清洗比例异常高 (ratio=%.3f)，可能过度清洗", article_id, result.removal_ratio)

        # 空结果检查
        if not text.strip():
            raise _handle_failure(repo, article_id, "清洗后文本为空")
        if not _has_analyzable_content(text):
            raise _handle_failure(repo, article_id, "清洗后未发现可分析正文，可能仅包含目录、导航或文档信息")

        # 截断保护
        if len(text) > config.max_text_length:
            text = text[: config.max_text_length] + f"\n\n[文本过长，已截断，原长度: {len(text)} 字符]"

        # 8. 写入数据库
        repo.save_cleaned_text(article_id=article_id, cleaned_text=text)
        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        repo.save_task_log(
            article_id=article_id,
            stage="cleaner",
            status="success",
            message=result.summary(),
            duration_ms=result.duration_ms,
        )

        logger.info("清洗完成 article_id=%s: %s", article_id, result.summary())
        return text

    except ValueError:
        raise
    except Exception as exc:
        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        raise _handle_failure(
            repo, article_id,
            f"清洗异常: {exc}",
            duration_ms=result.duration_ms,
        ) from exc


def _filter_low_density(text: str, config: CleanConfig) -> tuple[str, int]:
    """
    基于文本密度剔除低质量块（页眉、页脚、导航）。

    算法：
    1. 按 \\n\\n 分段
    2. 对每段计算中文字符占比
    3. 密度 < min_density_ratio 的段视为噪声 → 移除
    """
    paragraphs = text.split("\n\n")
    kept: list[str] = []
    removed_chars = 0

    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            kept.append(para)
            continue

        # 短段落：检查是否值得保留
        if len(stripped) < config.min_paragraph_chars:
            removed_chars += len(para)
            continue

        # 计算中文密度
        chinese_chars = len(re.findall(r"[一-鿿]", stripped))
        total_chars = len(stripped.replace(" ", ""))
        density = chinese_chars / max(total_chars, 1)

        if density < config.min_density_ratio:
            removed_chars += len(para)
        else:
            kept.append(para)

    return "\n\n".join(kept), removed_chars


def _has_analyzable_content(text: str) -> bool:
    """Reject outputs that only contain metadata, headings, navigation, or report links."""
    semantic_hints = (
        "观点", "逻辑", "建议", "操作", "策略", "展望", "预测", "预计", "预期",
        "价格", "上涨", "下跌", "上行", "下行", "偏强", "偏弱", "震荡",
        "库存", "需求", "供应", "成本", "利润", "基差", "现货", "期货",
        "利多", "利空", "支撑", "压力", "风险", "关注",
    )
    content_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("来源文件:", "解析器:")):
            continue
        content_lines.append(line)

    content = "\n".join(content_lines)
    if not content:
        return False
    if any(hint in content for hint in semantic_hints):
        return True
    return len(re.findall(r"[一-鿿]", content)) >= 30


def _handle_failure(
    repo: Any,
    article_id: int,
    message: str,
    duration_ms: int | None = None,
) -> ValueError:
    """统一处理清洗失败。"""
    try:
        repo.mark_failed(
            article_id=article_id,
            stage="cleaner",
            message=message,
            duration_ms=duration_ms,
        )
    except Exception as log_exc:
        logger.error("写入失败日志时异常: %s", log_exc)
    return ValueError(message)
