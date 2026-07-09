"""
pn05 LLM 文本精修模块

读取 cleaned_text，调用 LLM 将其改写成更自然、通俗的用户展示文本。
精修结果写入 article_texts.refined_text；cleaned_text 保持不变，继续作为分析和证据定位来源。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from pn07.models import LLMConfig

logger = logging.getLogger(__name__)

__all__ = ["refine_article", "build_refine_messages"]


SYSTEM_PROMPT = """你是一名中文财经研报编辑。请把清洗后的研报文本润色成通俗、自然、方便普通用户阅读的中文。

必须遵守：
1. 不改变原文含义，不新增原文没有的信息。
2. 保留所有关键事实、数字、品种名、合约、方向判断、因果逻辑和风险提示。
3. 可以整理语序、补足自然过渡、合并破碎句子，让表达更清楚。
4. 保留 Markdown 标题层级和表格；不要删除有分析价值的内容。
5. 只输出润色后的正文，不要解释、不要总结、不要使用代码块。"""


def refine_article(
    article_id: int,
    session: Any,
    *,
    config: LLMConfig | None = None,
) -> str | None:
    """
    精修单篇文章的 cleaned_text，写入 refined_text。

    精修是 best-effort 阶段：LLM 未配置、调用失败或返回空内容时，只写 task_log，
    不标记文章失败，也不覆盖既有 refined_text。
    """
    from back_end.app.repositories.articles import ArticleRepository

    config = config or LLMConfig.from_settings()
    repo = ArticleRepository(session)
    start_time = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - start_time) * 1000)

    try:
        article = repo.get_article_detail(article_id)
        if article is None or article.text is None:
            _log_failure(repo, article_id, "article 或 article_text 不存在", elapsed_ms())
            return None

        cleaned_text = article.text.cleaned_text or ""
        if not cleaned_text.strip():
            _log_failure(repo, article_id, "cleaned_text 为空", elapsed_ms())
            return None

        if not config.is_configured:
            _log_failure(repo, article_id, "LLM API 未配置，跳过精修", elapsed_ms())
            return None

        messages = build_refine_messages(cleaned_text, max_input_chars=config.max_input_chars)

        from pn07.llm_client import LLMAPIClient

        client = LLMAPIClient(config)
        raw_response = client.chat(messages, retries=config.max_retries)
        refined_text = _sanitize_refined_text(raw_response)
        if not refined_text:
            _log_failure(repo, article_id, "LLM 精修返回空文本", elapsed_ms())
            return None

        repo.save_refined_text(article_id=article_id, refined_text=refined_text)
        duration_ms = elapsed_ms()
        repo.save_task_log(
            article_id=article_id,
            stage="refiner",
            status="success",
            message=(
                f"[{duration_ms}ms] cleaned={len(cleaned_text)} "
                f"refined={len(refined_text)} model={config.model}"
            ),
            duration_ms=duration_ms,
        )
        logger.info("精修完成 article_id=%s refined=%s", article_id, len(refined_text))
        return refined_text

    except Exception as exc:
        duration_ms = elapsed_ms()
        logger.warning("精修失败 article_id=%s: %s", article_id, exc)
        _log_failure(repo, article_id, f"精修异常: {exc}", duration_ms)
        return None


def build_refine_messages(cleaned_text: str, *, max_input_chars: int = 8000) -> list[dict]:
    """构建文本精修 prompt。"""
    if len(cleaned_text) > max_input_chars:
        text = cleaned_text[:max_input_chars]
        text += f"\n\n[文本过长，已截断，原始长度: {len(cleaned_text)} 字符]"
    else:
        text = cleaned_text

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"请精修以下 cleaned_text：\n\n{text}"},
    ]


def _sanitize_refined_text(raw_response: str) -> str:
    """移除常见代码块包装，保留正文。"""
    text = (raw_response or "").strip()
    if not text:
        return ""

    fence_match = re.fullmatch(r"```(?:\w+)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    text = re.sub(r"^\s*(润色后[的正文]*|精修后[的正文]*|正文)\s*[:：]\s*", "", text).strip()
    return text


def _log_failure(repo: Any, article_id: int, message: str, duration_ms: int) -> None:
    try:
        repo.save_task_log(
            article_id=article_id,
            stage="refiner",
            status="failed",
            message=message,
            duration_ms=duration_ms,
        )
    except Exception as log_exc:
        logger.error("写入精修失败日志异常: %s", log_exc)
