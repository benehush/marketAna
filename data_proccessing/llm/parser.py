"""Strict parser for structured LLM fallback output."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any

from data_proccessing.catalog import PRODUCT_CATALOG, get_product, product_key_for_name
from data_proccessing.llm.diagnostics import sanitize_text
from data_proccessing.models import Direction


@dataclass(frozen=True, slots=True)
class LLMOutput:
    product_key: str
    product: str
    direction: Direction
    reason: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LLMParseError:
    error_type: str
    message: str
    field: str = ""
    value_excerpt: str = ""

    def to_dict(self, *, phase: str) -> dict[str, str]:
        return {
            "phase": phase,
            "error_type": self.error_type,
            "field": self.field,
            "message": self.message,
            "value_excerpt": self.value_excerpt,
        }


def parse_llm_response(
    raw: str,
    *,
    expected_product_key: str | None = None,
    expected_evidence_ids: set[str] | frozenset[str] | None = None,
) -> tuple[list[LLMOutput], list[LLMParseError]]:
    errors: list[LLMParseError] = []
    payload = _decode_json(raw, errors)
    if payload is None:
        return [], errors
    rows = payload.get("results") if isinstance(payload, dict) and isinstance(payload.get("results"), list) else [payload]
    outputs: list[LLMOutput] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(_error("invalid_json", f"result[{index}] 不是对象", field=f"results[{index}]", value=row))
            continue
        product_value = str(row.get("product") or row.get("product_key") or "").strip()
        product_key = str(row.get("product_key") or "").strip().upper() or product_key_for_name(product_value)
        product = get_product(product_key)
        if product is None:
            product = next((item for item in PRODUCT_CATALOG if product_value in {item.display_name, item.official_name, *item.aliases}), None)
        if product is None:
            errors.append(
                _error(
                    "product_mismatch",
                    f"result[{index}] 品种“{product_value or '空'}”无法识别",
                    field="product_key",
                    value=product_value,
                )
            )
            continue
        if expected_product_key and product.product_key != expected_product_key:
            errors.append(
                _error(
                    "product_mismatch",
                    f"product_key 返回“{product.product_key}”，期望“{expected_product_key}”",
                    field="product_key",
                    value=product.product_key,
                )
            )
            continue
        direction = _direction(row.get("direction"))
        if direction is None:
            errors.append(
                _error(
                    "invalid_direction",
                    f"direction 返回“{row.get('direction')}”，只允许看涨、看跌或中性",
                    field="direction",
                    value=row.get("direction"),
                )
            )
            continue
        reason_value = row.get("reason")
        reason = reason_value.strip() if isinstance(reason_value, str) else ""
        if not reason:
            errors.append(_error("empty_reason", "reason 必须是非空字符串", field="reason", value=reason_value))
            continue
        try:
            if isinstance(row.get("confidence"), bool):
                raise ValueError
            confidence = float(row.get("confidence"))
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(
                _error(
                    "invalid_confidence",
                    "confidence 必须是 0 到 1 之间的有限数字",
                    field="confidence",
                    value=row.get("confidence"),
                )
            )
            continue
        evidence_ids = _evidence_ids(
            row.get("evidence_ids"),
            expected=expected_evidence_ids,
            errors=errors,
            index=index,
        )
        if evidence_ids is None:
            continue
        outputs.append(
            LLMOutput(
                product.product_key,
                product.display_name,
                direction,
                reason,
                confidence,
                evidence_ids,
            )
        )
    return outputs, errors


def _decode_json(raw: str, errors: list[LLMParseError]) -> dict[str, Any] | None:
    candidate = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            candidate = match.group(0)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        errors.append(_error("invalid_json", f"JSON 格式无效：{exc.msg}", field="response", value=candidate))
        return None
    if not isinstance(payload, dict):
        errors.append(_error("invalid_json", "顶层 JSON 必须是对象", field="response", value=payload))
        return None
    return payload


def _direction(value: object) -> Direction | None:
    normalized = str(value).strip()
    return normalized if normalized in {"看涨", "看跌", "中性"} else None  # type: ignore[return-value]


def _evidence_ids(
    value: object,
    *,
    expected: set[str] | frozenset[str] | None,
    errors: list[LLMParseError],
    index: int,
) -> tuple[str, ...] | None:
    # Backward-compatible parser calls may omit the candidate set. Production
    # calls always provide it and therefore require evidence_ids.
    if expected is None:
        if value is None:
            return ()
        if not isinstance(value, list):
            errors.append(_error("invalid_evidence", "evidence_ids 必须是数组", field="evidence_ids", value=value))
            return None
        return tuple(str(item).strip() for item in value if str(item).strip())
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        errors.append(
            _error(
                "invalid_evidence",
                f"result[{index}] evidence_ids 必须包含1到3个证据编号",
                field="evidence_ids",
                value=value,
            )
        )
        return None
    normalized = tuple(str(item).strip() for item in value)
    if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        errors.append(_error("invalid_evidence", "evidence_ids 不能为空或重复", field="evidence_ids", value=value))
        return None
    unknown = [item for item in normalized if item not in expected]
    if unknown:
        errors.append(
            _error(
                "invalid_evidence",
                f"evidence_ids 包含未知编号：{', '.join(unknown)}",
                field="evidence_ids",
                value=value,
            )
        )
        return None
    return normalized


def _error(error_type: str, message: str, *, field: str, value: object) -> LLMParseError:
    return LLMParseError(
        error_type=error_type,
        message=sanitize_text(message, limit=1000),
        field=field,
        value_excerpt=sanitize_text(value, limit=120),
    )
