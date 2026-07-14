"""Build a small evidence-only prompt for LLM fallback."""

from __future__ import annotations

import json
from typing import Any, Sequence

from data_proccessing.config import ProcessingConfig
from data_proccessing.models import ArbitrationResult, EvidenceCandidate


def build_llm_context(
    *,
    title: str,
    product: str,
    arbitration: ArbitrationResult,
    config: ProcessingConfig | None = None,
    evidence_snippets: list[str] | tuple[str, ...] | None = None,
    evidence_candidates: list[EvidenceCandidate] | tuple[EvidenceCandidate, ...] | None = None,
) -> list[dict[str, str]]:
    config = config or ProcessingConfig()
    candidates = list(evidence_candidates or ())[:config.max_llm_snippets]
    source_snippets = evidence_snippets if evidence_snippets is not None else arbitration.evidence_snippets
    snippets = list(dict.fromkeys(source_snippets))[:config.max_llm_snippets]
    if candidates:
        evidence_payload: list[dict[str, str]] = [
            {"id": item.evidence_id, "quote": item.quote} for item in candidates
        ]
        context = "\n".join(f"- [{item.evidence_id}] {item.quote}" for item in candidates)
    else:
        evidence_payload = [
            {"id": f"E{index}", "quote": item}
            for index, item in enumerate(snippets, start=1)
        ]
        context = "\n".join(f"- [E{index}] {item}" for index, item in enumerate(snippets, start=1))
    context = context[:config.max_llm_chars]
    payload = {
        "product": product,
        "rule_scores": {
            "bullish": arbitration.bullish_score,
            "bearish": arbitration.bearish_score,
            "neutral": arbitration.neutral_score,
        },
        "rule_margin": arbitration.margin,
        "evidence": evidence_payload,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是期货市场研究员。只根据提供的证据判断该品种后续方向。"
                "必须返回 JSON：product_key、direction、reason、confidence、evidence_ids。"
                "direction 只能是 看涨、看跌、中性；不能补充证据外的事实。"
                "evidence_ids 必须选择1到3个给定证据编号，reason必须由所选证据支持。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"标题：{title}\n"
                f"待判断品种：{product}\n"
                f"规则摘要：{json.dumps(payload, ensure_ascii=False)}\n"
                f"相关原文证据：\n{context}"
            ),
        },
    ]


def build_llm_correction_context(
    messages: Sequence[dict[str, str]],
    *,
    raw_response: str,
    expected_product_key: str,
    product: str,
    parse_errors: Sequence[Any],
    allowed_evidence_ids: Sequence[str] = (),
) -> list[dict[str, str]]:
    """Append one constrained repair turn after structurally invalid output."""
    error_messages = [str(getattr(item, "message", item)) for item in parse_errors]
    schema = {
        "product_key": expected_product_key,
        "direction": "看涨|看跌|中性",
        "reason": "非空字符串",
        "confidence": 0.0,
        "evidence_ids": list(allowed_evidence_ids[:3]),
    }
    return [
        *messages,
        {"role": "assistant", "content": raw_response[:2000]},
        {
            "role": "user",
            "content": (
                f"上一次返回未通过校验：{'；'.join(error_messages)}。\n"
                f"请修正为品种 {product}（product_key 必须为 {expected_product_key}）。\n"
                f"evidence_ids 只能从 {list(allowed_evidence_ids)} 中选择1到3个且不得重复。\n"
                f"只返回一个合法 JSON 对象，不要 Markdown、解释或额外字段：\n"
                f"{json.dumps(schema, ensure_ascii=False)}\n"
                "confidence 必须是 0 到 1 之间的数字。"
            ),
        },
    ]
