"""
pn07 JSON 解析器

解析 LLM 返回的 JSON 输出，处理常见的格式异常：
- markdown 代码块包裹
- 前后多余文字
- 尾部多余逗号
- 单引号
- 字段缺失/非法值
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

DIRECTION_VALUES = ("看涨", "看跌", "中性")

def parse_llm_json(raw_response: str) -> tuple[dict, list[str]]:
    """
    解析 LLM 原始输出为 dict，并验证字段。

    Args:
        raw_response: LLM 原始返回文本

    Returns:
        (parsed_dict, errors): errors 为空列表表示解析完全成功
    """
    errors: list[str] = []
    text = raw_response.strip()

    # 1. 提取 JSON（尝试多种策略）
    json_str = _extract_json(text)

    # 2. 尝试解析
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试修复后再次解析
        json_str = _repair_json(json_str)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            return _empty_result(), [f"JSON 解析失败: {exc}"]

    raw_items = data.get("results") if isinstance(data, dict) else None
    if isinstance(raw_items, list):
        items = raw_items
    elif isinstance(data, dict):
        items = [data]
    else:
        return _empty_result(), ["JSON 根节点必须是对象或 results 数组"]

    parsed_items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"results[{index}] 不是对象")
            continue
        parsed, item_errors = _parse_item(item)
        errors.extend(f"results[{index}]: {error}" for error in item_errors)
        key = (parsed.get("product") or "", parsed.get("contract") or "")
        if parsed.get("product") and key in seen:
            errors.append(f"results[{index}]: 重复品种/合约 {key[0]} {key[1]}，已忽略")
            continue
        if parsed.get("product"):
            seen.add(key)
        parsed_items.append(parsed)

    primary = max(parsed_items, key=lambda item: item.get("confidence", 0.0), default=_empty_item())
    return {
        "product": primary.get("product"),
        "contract": primary.get("contract"),
        "direction": primary.get("direction"),
        "reason": primary.get("reason", ""),
        "confidence": primary.get("confidence", 0.0),
        "results": parsed_items,
    }, errors


def _parse_item(data: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    result: dict = {}

    product = data.get("product")
    if product and isinstance(product, str) and product.strip():
        result["product"] = product.strip()
    else:
        result["product"] = None
        errors.append("product 缺失或为空")

    contract = data.get("contract")
    result["contract"] = contract.strip() if isinstance(contract, str) and contract.strip() else None

    direction = data.get("direction")
    if direction and isinstance(direction, str):
        direction = direction.strip()
        if direction in DIRECTION_VALUES:
            result["direction"] = direction
        else:
            result["direction"] = None
            errors.append(f"direction 非法值: '{direction}'，允许: {DIRECTION_VALUES}")
    else:
        result["direction"] = None
        errors.append("direction 缺失或为空")

    reason = data.get("reason")
    if reason and isinstance(reason, str):
        result["reason"] = reason.strip()[:240]
    else:
        result["reason"] = ""
        errors.append("reason 缺失")

    confidence = data.get("confidence")
    try:
        conf = float(confidence) if confidence is not None else 0.0
        conf = max(0.0, min(1.0, conf))
        result["confidence"] = conf
    except (ValueError, TypeError):
        result["confidence"] = 0.0
        errors.append(f"confidence 非法值: {confidence}")

    return result, errors


# ---- 内部 ----

def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 字符串。"""
    # 策略1: ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 策略2: 找到第一个 { 和最后一个 } 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    # 策略3: 返回原文本
    return text


def _repair_json(json_str: str) -> str:
    """尝试修复常见的 JSON 格式问题。"""
    # 尾部多余逗号 (在 } 或 ] 前)
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

    # 单引号 → 双引号（但保留字符串内的单引号）
    # 简单策略：将键和值的单引号替换
    # 'key': → "key":
    json_str = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', json_str)
    # : 'value' → : "value"
    json_str = re.sub(r"(:\s*)'([^']*)'", r'\1"\2"', json_str)

    # 移除注释行
    json_str = re.sub(r"//.*$", "", json_str, flags=re.MULTILINE)

    return json_str.strip()


def _empty_result() -> dict:
    item = _empty_item()
    return {**item, "results": [item]}


def _empty_item() -> dict:
    return {"product": None, "contract": None, "direction": None, "reason": "", "confidence": 0.0}
