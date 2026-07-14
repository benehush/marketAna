"""Best-effort LLM fallback for unresolved product blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
import time
from typing import Any

from pn06.product_catalog import PRODUCT_CATALOG, get_product
from pn07.models import LLMConfig

logger = logging.getLogger(__name__)

AUTO_RESOLVE_THRESHOLD = 0.85


@dataclass(slots=True)
class ProductResolutionResult:
    article_id: int
    attempted: int = 0
    resolved: int = 0
    pending: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


def resolve_article_products(
    article_id: int,
    session: Any,
    *,
    config: LLMConfig | None = None,
    auto_threshold: float = AUTO_RESOLVE_THRESHOLD,
) -> ProductResolutionResult:
    """Resolve every pending block in one constrained LLM request.

    This stage never marks the article failed.  Unknown blocks remain available
    for manual review when configuration, transport or parsing fails.
    """
    from back_end.app.repositories.articles import ArticleRepository
    from back_end.app.repositories.products import ProductRepository

    started = time.monotonic()
    article_repo = ArticleRepository(session)
    product_repo = ProductRepository(session)
    pending = product_repo.pending_resolutions_for_article(article_id)
    result = ProductResolutionResult(article_id=article_id, attempted=len(pending))
    if not pending:
        return result

    config = config or LLMConfig.from_settings()
    if not config.is_configured:
        result.pending = len(pending)
        result.errors.append("LLM API 未配置")
        _write_log(article_repo, article_id, result, "warning")
        return result

    messages = _build_messages(pending)
    try:
        from pn07.llm_client import LLMAPIClient

        raw = LLMAPIClient(config).chat(messages, retries=config.max_retries)
        items, errors = parse_resolution_json(raw)
        result.errors.extend(errors)
        by_ref = {str(item.id): item for item in pending}
        handled: set[str] = set()
        for item in items:
            block_ref = str(item.get("block_ref") or "")
            resolution = by_ref.get(block_ref)
            if resolution is None or block_ref in handled:
                result.errors.append(f"无效或重复 block_ref: {block_ref or '<empty>'}")
                continue
            handled.add(block_ref)
            accepted = product_repo.apply_llm_resolution(
                resolution,
                product_key=item.get("product_key"),
                confidence=float(item.get("confidence") or 0.0),
                auto_threshold=auto_threshold,
            )
            if accepted:
                result.resolved += 1
            else:
                result.pending += 1
        result.pending += len(pending) - len(handled)
    except Exception as exc:
        logger.warning("ProductResolver best-effort failure article_id=%s: %s", article_id, exc)
        result.errors.append(str(exc))
        result.pending = len(pending)

    result.duration_ms = int((time.monotonic() - started) * 1000)
    _write_log(article_repo, article_id, result, "warning" if result.errors else "success")
    return result


def _build_messages(resolutions: list[Any]) -> list[dict[str, str]]:
    catalog = "\n".join(
        f"- {item.product_key} | {item.display_name} | {item.official_name} | {item.symbol or 'aggregate'}"
        for item in PRODUCT_CATALOG
    )
    blocks = "\n\n".join(
        (
            f"block_ref={item.id}\n"
            f"raw_name={item.raw_name or '无明确标题'}\n"
            f"text={str(item.excerpt or '')[:600]}"
        )
        for item in resolutions
    )
    system = (
        "你是期货品种归一化器。只能从给定目录选择 product_key；无法确定时返回 unknown。"
        "不要推断走势，不要创造目录外品种。只输出 JSON。"
        '格式：{"results":[{"block_ref":"","raw_name":"","product_key":"unknown",'
        '"confidence":0.0,"status":"resolved/unknown"}]}'
    )
    user = f"标准品种目录：\n{catalog}\n\n待归一化片段：\n{blocks}\n\n请输出 JSON："
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_resolution_json(raw: str) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    text = (raw or "").strip()
    code = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if code:
        text = code.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"ProductResolver JSON 解析失败: {exc}"]
    raw_items = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return [], ["ProductResolver results 必须是数组"]
    parsed: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            errors.append(f"results[{index}] 不是对象")
            continue
        product_key = str(item.get("product_key") or "unknown").strip().upper()
        status = str(item.get("status") or "unknown").strip().lower()
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
            errors.append(f"results[{index}] confidence 非法")
        if product_key != "UNKNOWN" and get_product(product_key) is None:
            errors.append(f"results[{index}] 目录外 product_key: {product_key}")
            product_key = "UNKNOWN"
            confidence = 0.0
            status = "unknown"
        parsed.append(
            {
                "block_ref": str(item.get("block_ref") or ""),
                "raw_name": str(item.get("raw_name") or "")[:255],
                "product_key": None if product_key == "UNKNOWN" else product_key,
                "confidence": confidence,
                "status": status,
            }
        )
    return parsed, errors


def _write_log(repo: Any, article_id: int, result: ProductResolutionResult, status: str) -> None:
    result.duration_ms = result.duration_ms or 0
    repo.save_task_log(
        article_id=article_id,
        stage="product_resolver",
        status=status,
        message=(
            f"attempted={result.attempted} resolved={result.resolved} pending={result.pending} "
            f"errors={'; '.join(result.errors) if result.errors else ''}"
        ),
        duration_ms=result.duration_ms,
    )
