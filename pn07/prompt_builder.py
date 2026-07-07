"""
pn07 Prompt 构建器

组装 System/User prompt，将文章上下文注入模板。
"""

from __future__ import annotations


SYSTEM_PROMPT = """你是一位资深期货市场分析师。请从以下期货研究报告文本中提取关键信息，并以 JSON 格式输出分析结果。

规则：
1. 输出一个 results 数组；每个元素对应一个明确期货品种或品种+合约观点。
2. product: 品种名称；contract: 合约（没有则为空字符串）。
3. direction: 走势预测，必须是"看涨"、"看跌"或"中性"之一。
4. reason: 支撑该判断的核心理由，控制在120字以内，引用文本中的关键信息。
5. confidence: 你对该判断的置信度(0.0-1.0)。明确信号>0.8，模糊信号<0.5，不确定时给低分。
6. 如果文本提到多个品种，请输出多条结果；不要把不同品种的方向混合成一条。

只输出 JSON，不要添加任何解释或额外文本。
格式：{"results":[{"product":"","contract":"","direction":"看涨/看跌/中性","reason":"","confidence":0.0}]}"""


def build_messages(
    cleaned_text: str,
    *,
    title: str = "",
    source: str = "",
    company: str = "",
    publish_time: str = "",
    max_input_chars: int = 8000,
    rule_candidates: list[dict] | None = None,
) -> list[dict]:
    """
    构建 LLM messages。

    Args:
        cleaned_text: 清洗后的文章正文
        title: 文章标题
        source: 来源
        company: 期货公司
        publish_time: 发布时间
        max_input_chars: 正文最大字符数（超出截断）

    Returns:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
    """
    # 构建用户消息
    parts = []
    if title:
        parts.append(f"标题：{title}")
    meta_parts = []
    if source:
        meta_parts.append(f"来源：{source}")
    if company:
        meta_parts.append(f"期货公司：{company}")
    if publish_time:
        meta_parts.append(f"发布时间：{publish_time}")
    if meta_parts:
        parts.append(" | ".join(meta_parts))

    if rule_candidates:
        lines = []
        for item in rule_candidates:
            lines.append(
                f"- {item.get('product') or '未知'} "
                f"{item.get('contract') or ''} "
                f"{item.get('direction') or '未定'} "
                f"confidence={float(item.get('confidence') or 0):.2f}"
            )
        parts.append("规则引擎候选（请保留高置信结果，补全低置信或遗漏品种）：\n" + "\n".join(lines))

    # 正文（可能截断）
    if len(cleaned_text) > max_input_chars:
        truncated = cleaned_text[:max_input_chars]
        truncated += f"\n\n[文本过长，已截断，原始长度: {len(cleaned_text)} 字符]"
    else:
        truncated = cleaned_text

    parts.append(f"\n正文：\n{truncated}")
    parts.append("\n请输出 JSON：")

    user_content = "\n".join(parts)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
