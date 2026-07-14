"""
LLM-assisted cleanup for rule-engine reasons.

This stage only polishes the conclusion basis for display. It must never change
the rule engine's product, direction, or confidence, and it always falls back to
deterministic cleanup if the LLM is unavailable or unsafe.
"""

from __future__ import annotations

from dataclasses import replace
import logging
import re
import time
from typing import Any

from pn05.display_cleaner import clean_display_text, has_residual_display_noise
from pn07.models import LLMConfig

logger = logging.getLogger(__name__)

__all__ = ["refine_rule_reason", "build_reason_refine_messages"]

_INVALID_REASON_PATTERNS = (
    "注：",
    "注:",
    "原文可能有误",
    "建议核实",
    "数据缺失",
    "逻辑存疑",
    "自我修正",
    "更正：",
    "更正:",
    "作为模型",
    "我是AI",
    "我是 AI",
    "我无法",
    "以下是",
)

SYSTEM_PROMPT = """你是一名中文财经研报编辑。请把规则引擎提取的“结论依据”整理成给普通用户看的简洁中文。

必须遵守：
1. 只依据输入文本，不新增事实，不改变品种、方向和市场判断。
2. 删除分析师证号、邮箱、电话、网址、地址、免责声明、页眉页脚、页码等无关信息。
3. 输出 1-2 句紧凑段落，保留关键因果和操作建议。
4. 不要输出标题、项目符号、解释、免责声明或代码块。"""


def refine_rule_reason(
    *,
    article_id: int,
    repo: Any,
    product: str,
    direction: str,
    reason: str,
    source_text: str,
    enable_llm: bool,
    config: LLMConfig | None = None,
) -> str:
    """Return an LLM-polished reason, falling back to deterministic cleanup."""
    start = time.monotonic()
    fallback = clean_display_text(reason or source_text, max_chars=260)
    if not fallback:
        fallback = f"规则识别: {direction}"

    if not enable_llm:
        return fallback

    llm_config = config or LLMConfig.from_settings()
    if not llm_config.is_configured:
        _log(repo, article_id, "skipped", "LLM API 未配置，使用规则依据净化结果", start)
        return fallback

    try:
        refine_config = replace(
            llm_config,
            max_tokens=max(llm_config.max_tokens, 400),
            temperature=min(llm_config.temperature, 0.1),
        )
        setattr(refine_config, "enable_thinking", False)

        from pn07.llm_client import LLMAPIClient

        client = LLMAPIClient(refine_config)
        raw_response = client.chat(
            build_reason_refine_messages(
                product=product,
                direction=direction,
                reason=reason,
                source_text=source_text,
            ),
            retries=refine_config.max_retries,
        )
        refined = _sanitize_reason(raw_response)
        invalid_reason = _validate_reason(refined)
        if invalid_reason:
            _log(repo, article_id, "fallback", f"LLM reason 输出不安全：{invalid_reason}", start)
            return fallback

        _log(repo, article_id, "success", f"product={product} direction={direction} refined={len(refined)}", start)
        return refined
    except Exception as exc:
        logger.warning("规则 reason 精修失败 article_id=%s product=%s: %s", article_id, product, exc)
        _log(repo, article_id, "fallback", f"LLM reason 精修失败，使用规则依据净化结果: {exc}", start)
        return fallback


def build_reason_refine_messages(
    *,
    product: str,
    direction: str,
    reason: str,
    source_text: str,
) -> list[dict]:
    source = clean_display_text(source_text, max_chars=900)
    basis = clean_display_text(reason, max_chars=500)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"品种：{product}\n"
                f"方向：{direction}\n"
                f"规则提取依据：{basis}\n"
                f"品种正文片段：{source}\n\n"
                "请输出干净的结论依据，1-2句即可。\n\n/no_think"
            ),
        },
    ]


def _sanitize_reason(raw_response: str) -> str:
    text = (raw_response or "").strip()
    if not text:
        return ""
    fence_match = re.fullmatch(r"```(?:\w+)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    text = re.sub(r"^\s*(结论依据|依据|整理后|精修后)\s*[:：]\s*", "", text).strip()
    return clean_display_text(text, max_chars=260)


def _validate_reason(text: str) -> str:
    if not text:
        return "返回空文本"
    if has_residual_display_noise(text):
        return "包含资质、联系方式或免责声明噪声"
    if len(text) > 280:
        return f"输出过长 reason={len(text)}"
    for pattern in _INVALID_REASON_PATTERNS:
        if pattern in text:
            return f"包含禁用表达 {pattern}"
    return ""


def _log(repo: Any, article_id: int, status: str, message: str, start: float) -> None:
    try:
        repo.save_task_log(
            article_id=article_id,
            stage="reason_refiner",
            status=status,
            message=message,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        logger.error("写入 reason_refiner 日志失败: %s", exc)
