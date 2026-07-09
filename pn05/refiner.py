"""
pn05 LLM 文本精修模块

读取 cleaned_text，调用 LLM 将其改写成更自然、通俗的用户展示文本。
精修结果写入 article_texts.refined_text；cleaned_text 保持不变，继续作为分析和证据定位来源。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from typing import Any

from pn07.models import LLMConfig

logger = logging.getLogger(__name__)

__all__ = ["refine_article", "build_refine_messages"]

REFINE_CHUNK_CHARS = 1200
REFINED_MAX_EXPANSION_RATIO = 1.15
REFINED_MAX_EXPANSION_CHARS = 200
_INVALID_REFINED_PATTERNS = (
    "注：", "注:", "原文可能有误", "建议核实", "数据缺失", "逻辑存疑",
    "自我修正", "更正：", "更正:", "原文数据", "依据指令", "不改变原文含义",
    "作为模型", "我是AI", "我是 AI", "我无法", "以下是", "润色如下",
)


SYSTEM_PROMPT = """你是一名中文财经研报编辑。请把清洗后的研报文本润色成通俗、自然、方便普通用户阅读的中文。

必须遵守：
1. 不改变原文含义，不新增原文没有的信息。
2. 保留所有关键事实、数字、品种名、合约、方向判断、因果逻辑和风险提示。
3. 只做保守顺句和轻量整理；不要纠错、不要补全缺失内容、不要推断数字、不要改写方向判断。
4. 保留原有 Markdown 标题层级；不要新增项目符号、解释段、摘要或结论。
5. 禁止输出“注：”“原文可能有误”“建议核实”“数据缺失”“逻辑存疑”“自我修正”“更正：”等解释或纠错文本。
6. 输出长度原则上不超过输入；只输出润色后的正文，不要解释、不要总结、不要使用代码块。"""


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

        refine_config = replace(config, max_tokens=max(config.max_tokens, 2000))
        setattr(refine_config, "enable_thinking", False)

        from pn07.llm_client import LLMAPIClient

        client = LLMAPIClient(refine_config)
        refined_parts: list[str] = []
        chunks = _split_refine_chunks(cleaned_text, max_chars=REFINE_CHUNK_CHARS)
        for index, chunk in enumerate(chunks, start=1):
            messages = build_refine_messages(
                chunk,
                max_input_chars=min(refine_config.max_input_chars, REFINE_CHUNK_CHARS),
                chunk_index=index,
                chunk_count=len(chunks),
            )
            raw_response = client.chat(messages, retries=refine_config.max_retries)
            refined_part = _sanitize_refined_text(raw_response)
            if not refined_part:
                _log_failure(
                    repo,
                    article_id,
                    (
                        f"LLM 精修第 {index}/{len(chunks)} 段返回空文本，"
                        "可能是模型未产出 message.content 或输出预算不足"
                    ),
                    elapsed_ms(),
                )
                return None
            invalid_reason = _validate_refined_text(refined_part, chunk)
            if invalid_reason:
                _log_failure(
                    repo,
                    article_id,
                    f"LLM 精修第 {index}/{len(chunks)} 段输出不安全：{invalid_reason}",
                    elapsed_ms(),
                )
                return None
            refined_parts.append(refined_part)

        refined_text = "\n\n".join(refined_parts).strip()

        repo.save_refined_text(article_id=article_id, refined_text=refined_text)
        duration_ms = elapsed_ms()
        repo.save_task_log(
            article_id=article_id,
            stage="refiner",
            status="success",
            message=(
                f"[{duration_ms}ms] cleaned={len(cleaned_text)} "
                f"refined={len(refined_text)} model={refine_config.model}"
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


def build_refine_messages(
    cleaned_text: str,
    *,
    max_input_chars: int = 8000,
    chunk_index: int = 1,
    chunk_count: int = 1,
) -> list[dict]:
    """构建文本精修 prompt。"""
    if len(cleaned_text) > max_input_chars:
        text = cleaned_text[:max_input_chars]
        text += f"\n\n[文本过长，已截断，原始长度: {len(cleaned_text)} 字符]"
    else:
        text = cleaned_text

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"请精修以下 cleaned_text 第 {chunk_index}/{chunk_count} 段。"
                "仅润色本段，不要补写其他段落；如果原文疑似错位或缺失，只保守顺句，"
                "不要说明、不要纠错、不要补数字：\n\n"
                f"{text}\n\n/no_think"
            ),
        },
    ]


def _split_refine_chunks(text: str, *, max_chars: int) -> list[str]:
    """按空行/行边界切分精修文本，降低单次 LLM 请求负担。"""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    blocks = re.split(r"(\n\n+)", text)
    for block in blocks:
        if not block:
            continue
        if current and current_len + len(block) > max_chars:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        if len(block) > max_chars:
            for line in block.splitlines(keepends=True):
                if current and current_len + len(line) > max_chars:
                    chunks.append("".join(current).strip())
                    current = []
                    current_len = 0
                current.append(line)
                current_len += len(line)
            continue
        current.append(block)
        current_len += len(block)

    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


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


def _validate_refined_text(refined_text: str, source_chunk: str) -> str:
    text = (refined_text or "").strip()
    if not text:
        return "返回空文本"
    compact = re.sub(r"\s+", "", text)
    if compact in {"润色后的正文", "精修后的正文", "正文"}:
        return "只有包装语"
    for pattern in _INVALID_REFINED_PATTERNS:
        if pattern in text:
            return f"包含禁用表达 {pattern}"

    max_len = int(len(source_chunk) * REFINED_MAX_EXPANSION_RATIO + REFINED_MAX_EXPANSION_CHARS)
    if len(text) > max_len:
        return f"输出过长 refined={len(text)} limit={max_len}"
    return ""


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
