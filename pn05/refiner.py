"""
pn05 LLM 文本精修模块

读取按品种切分后的 cleaned_text，调用 LLM 将其改写成更自然、通俗的用户展示文本。
精修结果写入 article_product_segments.refined_text；article_texts.cleaned_text 保持不变，
继续作为分析和证据定位来源。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from typing import Any

from pn05.display_cleaner import clean_display_text, has_residual_display_noise
from pn07.models import LLMConfig

logger = logging.getLogger(__name__)

__all__ = ["refine_article", "build_refine_messages"]

REFINE_CHUNK_CHARS = 1500
REFINED_MAX_EXPANSION_RATIO = 1.15
REFINED_MAX_EXPANSION_CHARS = 200
_INVALID_REFINED_PATTERNS = (
    "注：", "注:", "原文可能有误", "建议核实", "数据缺失", "逻辑存疑",
    "自我修正", "更正：", "更正:", "原文数据", "依据指令", "不改变原文含义",
    "作为模型", "我是AI", "我是 AI", "我无法", "以下是", "润色如下",
)


SYSTEM_PROMPT = """你是一名中文财经研报编辑。请把清洗后的研报文本润色成紧凑、自然、方便普通用户阅读的中文。

必须遵守：
1. 不改变原文含义，不新增原文没有的信息。
2. 保留所有关键事实、数字、品种名、合约、方向判断、因果逻辑和风险提示。
3. 只做保守顺句和轻量整理；不要纠错、不要补全缺失内容、不要推断数字、不要改写方向判断。
4. 删除分析师证号、邮箱、电话、网址、地址、免责声明、页眉页脚和页码等无关信息。
5. 保留原有 Markdown 标题层级，但输出为紧凑段落；不要保留连续空行，不要新增项目符号、解释段、摘要或结论。
6. 禁止输出“注：”“原文可能有误”“建议核实”“数据缺失”“逻辑存疑”“自我修正”“更正：”等解释或纠错文本。
7. 输出长度原则上不超过输入；只输出润色后的正文，不要解释、不要总结、不要使用代码块。"""


def refine_article(
    article_id: int,
    session: Any,
    *,
    config: LLMConfig | None = None,
) -> str | None:
    """
    精修单篇文章的有效品种分段，写入 article_product_segments.refined_text。

    精修是 best-effort 阶段：LLM 未配置、调用失败或返回空内容时，只写 task_log，
    不标记文章失败，也不覆盖既有 refined_text。返回值是本次成功精修的分段文本拼接，
    供手动流水线输出使用；不再写入 article_texts.refined_text。
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

        segments = _refinable_product_segments(repo.get_product_segments(article_id))
        if not segments:
            duration_ms = elapsed_ms()
            repo.save_task_log(
                article_id=article_id,
                stage="refiner",
                status="skipped",
                message=f"[{duration_ms}ms] 无可精修的有效品种分段，跳过全文精修",
                duration_ms=duration_ms,
            )
            logger.info("精修跳过 article_id=%s: 无有效品种分段", article_id)
            return None

        refined_segments: list[str] = []
        failed_segment_count = 0
        for segment in segments:
            refined_segment = _refine_text(
                client,
                refine_config,
                segment.cleaned_text or "",
                repo=repo,
                article_id=article_id,
                label=f"品种分段 {segment.segment_index + 1}/{len(segments)} {segment.product}",
                elapsed_ms=elapsed_ms,
            )
            if refined_segment is None:
                # Segment display text is optional.  Keep later analysis moving
                # even when a single product-level call fails.
                failed_segment_count += 1
                continue
            segment.refined_text = refined_segment
            segment.refined_length = len(refined_segment)
            refined_segments.append(refined_segment)

        duration_ms = elapsed_ms()
        if not refined_segments:
            _log_failure(
                repo,
                article_id,
                f"分段精修全部失败 segments={len(segments)} model={refine_config.model}",
                duration_ms,
            )
            return None

        repo.save_task_log(
            article_id=article_id,
            stage="refiner",
            status="success",
            message=(
                f"[{duration_ms}ms] segments={len(segments)} "
                f"segment_refined={len(refined_segments)} segment_failed={failed_segment_count} "
                f"model={refine_config.model}"
            ),
            duration_ms=duration_ms,
        )
        logger.info(
            "分段精修完成 article_id=%s segments=%s refined=%s",
            article_id,
            len(segments),
            len(refined_segments),
        )
        return "\n\n".join(refined_segments)

    except Exception as exc:
        duration_ms = elapsed_ms()
        logger.warning("精修失败 article_id=%s: %s", article_id, exc)
        _log_failure(repo, article_id, f"精修异常: {exc}", duration_ms)
        return None


def _refinable_product_segments(segments: list[Any]) -> list[Any]:
    """Return recognized product segments that can feed user-facing evidence."""
    return [
        segment
        for segment in segments
        if (
            segment.section_type != "unknown"
            and segment.product != "未知"
            and (segment.cleaned_text or "").strip()
        )
    ]


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
                "删除资质证号、联系方式、页眉页脚、免责声明和多余空行；"
                "不要说明、不要纠错、不要补数字：\n\n"
                f"{text}\n\n/no_think"
            ),
        },
    ]


def _normalize_refine_source(text: str) -> str:
    """Remove PDF/OCR soft wraps while retaining real paragraph boundaries.

    ``cleaned_text`` often still carries physical PDF line wraps.  They are
    not semantic paragraph boundaries: joining them first prevents a chunk
    from starting with a sentence suffix such as ``比去库`` or ``吨``.
    """
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append("".join(current).strip())
            current.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush()
            continue
        # Markdown and bracket headings denote a genuine structural boundary.
        if re.match(r"^#{1,6}\s+", line) or re.match(r"^【[^】]{1,40}】", line):
            flush()
            paragraphs.append(line)
            continue
        current.append(line)
    flush()
    return "\n\n".join(part for part in paragraphs if part)


def _split_refine_chunks(text: str, *, max_chars: int) -> list[str]:
    """Split only at semantic boundaries, never merely at PDF line wraps."""
    if max_chars <= 0:
        raise ValueError("max_chars 必须大于 0")

    normalized = _normalize_refine_source(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    blocks = re.split(r"(\n\n+)", normalized)
    for block in blocks:
        if not block:
            continue
        if current and current_len + len(block) > max_chars:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        if len(block) > max_chars:
            for piece in _split_long_refine_block(block, max_chars=max_chars):
                if current and current_len + len(piece) > max_chars:
                    chunks.append("".join(current).strip())
                    current = []
                    current_len = 0
                current.append(piece)
                current_len += len(piece)
            continue
        current.append(block)
        current_len += len(block)

    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _split_long_refine_block(block: str, *, max_chars: int) -> list[str]:
    """Split a long paragraph at sentence punctuation, then clause punctuation."""
    remaining = block.strip()
    pieces: list[str] = []
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = max((window.rfind(mark) for mark in "。！？；"), default=-1)
        # A very early sentence boundary creates inefficient tiny chunks;
        # in that case prefer a later clause boundary before a last-resort cut.
        if cut < max_chars // 2:
            clause_cut = max((window.rfind(mark) for mark in "，、："), default=-1)
            if clause_cut >= max_chars // 2:
                cut = clause_cut
        if cut >= 0:
            cut += 1
        else:
            cut = max_chars
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _refine_text(
    client: Any,
    refine_config: LLMConfig,
    source_text: str,
    *,
    repo: Any,
    article_id: int,
    label: str,
    elapsed_ms: Any,
) -> str | None:
    refined_parts: list[str] = []
    chunks = _split_refine_chunks(source_text, max_chars=REFINE_CHUNK_CHARS)
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
                    f"LLM 精修{label}第 {index}/{len(chunks)} 段返回空文本，"
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
                f"LLM 精修{label}第 {index}/{len(chunks)} 段输出不安全：{invalid_reason}",
                elapsed_ms(),
            )
            return None
        refined_parts.append(refined_part)
    return clean_display_text("\n".join(refined_parts))


def _sanitize_refined_text(raw_response: str) -> str:
    """移除常见代码块包装，保留正文。"""
    text = (raw_response or "").strip()
    if not text:
        return ""

    fence_match = re.fullmatch(r"```(?:\w+)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    text = re.sub(r"^\s*(润色后[的正文]*|精修后[的正文]*|正文)\s*[:：]\s*", "", text).strip()
    return clean_display_text(text)


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
    if has_residual_display_noise(text):
        return "包含资质、联系方式或免责声明噪声"

    source_for_check = re.sub(r"\s+", "", clean_display_text(source_chunk))
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?", source_for_check))
    output_numbers = set(re.findall(r"\d+(?:\.\d+)?", compact))
    missing_numbers = sorted(source_numbers - output_numbers)
    if missing_numbers:
        return f"关键数值缺失: {', '.join(missing_numbers[:5])}"

    # The refiner is a conservative copy-editing step, not a summarizer.
    # Reject outputs that are implausibly short, which otherwise look valid
    # while silently dropping a later paragraph or an entire product block.
    if len(source_for_check) >= 120 and len(compact) < len(source_for_check) * 0.45:
        return f"输出疑似遗漏正文 refined={len(compact)} source={len(source_for_check)}"

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
