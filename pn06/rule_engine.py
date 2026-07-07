"""
pn06 规则识别引擎

识别期货品种、走势方向和置信度。
高置信（≥0.7）直接入库，低置信标记 need_llm 交由 pn07 处理。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from back_end.app.core.status import ArticleProcessingStatus

from pn06.confidence import calculate_confidence
from pn06.direction_rules import detect_direction, extract_reason
from pn06.models import RuleBatchResult, RuleConfig, RuleResult
from pn06.product_dict import detect_products

logger = logging.getLogger(__name__)

__all__ = ["analyze_article", "RuleConfig"]


def analyze_article(
    article_id: int,
    session: Any,
    *,
    config: RuleConfig | None = None,
) -> RuleBatchResult:
    """
    对单篇文章的 cleaned_text 执行规则识别。

    流程:
    1. 读取 article_texts.cleaned_text
    2. 品种检测
    3. 方向检测
    4. 理由提取
    5. 置信度计算
    6. 高置信 → 直接入库 (mark_stored)
       低置信 → status=3, need_llm=True
    7. 写 task_log

    Args:
        article_id: 文章 ID
        session: SQLAlchemy Session
        config: 规则配置

    Returns:
        RuleBatchResult: 识别结果
    """
    from back_end.app.repositories.articles import ArticleRepository

    config = config or RuleConfig()
    repo = ArticleRepository(session)
    start_time = time.monotonic()

    # 1. 读取 cleaned_text
    article = repo.get_article_detail(article_id)
    if article is None or article.text is None:
        raise _fail(repo, article_id, "article 或 article_text 不存在")

    cleaned_text = article.text.cleaned_text or ""
    if not cleaned_text.strip():
        raise _fail(repo, article_id, "cleaned_text 为空")

    try:
        # 2-5. 按 05 清洗后的 Markdown/小节切片做局部识别
        candidates = _build_product_candidates(cleaned_text)
        results: list[RuleResult] = []
        for candidate in candidates:
            product = candidate["product"]
            section_text = candidate["text"]
            contract = candidate.get("contract")
            dir_result = detect_direction(section_text)
            direction = dir_result["direction"]
            reason = extract_reason(section_text, direction, config.reason_window)
            if not reason and direction:
                reason = _compact_reason(section_text)
            confidence = calculate_confidence(product, dir_result, config)
            need_llm = confidence < config.confidence_threshold or not direction or dir_result.get("is_conflict", False)
            results.append(
                RuleResult(
                    product=product,
                    direction=direction,
                    reason=reason,
                    confidence=confidence,
                    need_llm=need_llm,
                    detail={
                        **dir_result,
                        "contract": contract,
                    },
                )
            )

        need_llm_products = [
            result.product or "未知"
            for result in results
            if result.need_llm
        ]
        if not results:
            need_llm_products = ["未知"]

        result = RuleBatchResult(results=results, need_llm_products=need_llm_products)

        # 6. 决策：全部高置信则直接完成；部分低置信则只暂存高置信结果并交由 LLM 补全
        high_results = result.high_confidence_results
        if high_results:
            primary = max(high_results, key=lambda item: item.confidence)
            repo.save_analysis_results(
                article_id,
                [
                    {
                        "product": item.product,
                        "contract": item.detail.get("contract"),
                        "direction": item.direction,
                        "reason": item.reason or f"规则识别: {item.direction}",
                        "confidence": item.confidence,
                        "analysis_method": "rule",
                        "need_manual_review": False,
                        "is_primary": item is primary,
                    }
                    for item in high_results
                    if item.product and item.direction
                ],
                mark_stored=not result.need_llm,
            )

        if result.need_llm:
            repo.update_status(article_id, ArticleProcessingStatus.RULE_ANALYZED)

        # 7. task_log
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        repo.save_task_log(
            article_id=article_id,
            stage="rule_engine",
            status="success",
            message=result.summary(),
            duration_ms=elapsed_ms,
        )

        logger.info("规则识别完成 article_id=%s: %s", article_id, result.summary())
        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        raise _fail(repo, article_id, f"规则识别异常: {exc}", duration_ms=elapsed_ms) from exc


def _fail(repo: Any, article_id: int, msg: str, duration_ms: int | None = None) -> ValueError:
    try:
        repo.mark_failed(article_id=article_id, stage="rule_engine", message=msg, duration_ms=duration_ms)
    except Exception as e:
        logger.error("写入失败日志异常: %s", e)
    return ValueError(msg)


def _build_product_candidates(text: str) -> list[dict[str, str | None]]:
    """按小节/品种提及构建每个品种的局部文本。"""
    sections = _split_markdown_sections(text)
    candidates: dict[tuple[str, str], dict[str, Any]] = {}

    for section in sections:
        for product in detect_products(section):
            product_window = _local_product_window(section, product)
            local_text = product_window or section
            contract = _extract_contract(local_text)
            key = (product, _contract_key(contract))
            candidates.setdefault(key, {"product": product, "contract": contract, "parts": []})
            candidates[key]["parts"].append(local_text)

    if not candidates:
        for product in detect_products(text):
            local_text = _local_product_window(text, product) or text
            contract = _extract_contract(local_text)
            key = (product, _contract_key(contract))
            candidates.setdefault(key, {"product": product, "contract": contract, "parts": []})
            candidates[key]["parts"].append(local_text)

    return [
        {
            "product": str(candidate["product"]),
            "contract": candidate["contract"],
            "text": "\n".join(candidate["parts"]),
        }
        for candidate in candidates.values()
        if any(str(part).strip() for part in candidate["parts"])
    ]


def _split_markdown_sections(text: str) -> list[str]:
    """识别 05 cleaned_text 中的 Markdown 小节和【品种】段落。"""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                current.append("")
            continue

        pieces = _split_bracket_sections(stripped)
        for idx, piece in enumerate(pieces):
            starts_section = piece.startswith("#") or piece.startswith("## ") or bool(re.match(r"^【[^】]{1,20}】", piece))
            if starts_section and current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(piece)
            if idx < len(pieces) - 1 and current:
                blocks.append("\n".join(current).strip())
                current = []

    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _split_bracket_sections(line: str) -> list[str]:
    matches = list(re.finditer(r"【[^】]{1,20}】", line))
    if len(matches) <= 1:
        return [line]
    pieces: list[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        prefix = line[:start].strip() if index == 0 else ""
        if prefix:
            pieces.append(prefix)
        pieces.append(line[start:end].strip())
    return [piece for piece in pieces if piece]


def _local_product_window(text: str, product: str, radius: int = 3) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return text
    indices = [idx for idx, sentence in enumerate(sentences) if product in sentence or any(alias in sentence for alias in _product_aliases(product))]
    if not indices:
        return text
    selected: set[int] = set()
    for idx in indices:
        selected.update(range(max(0, idx - radius), min(len(sentences), idx + radius + 1)))
    return "".join(sentences[idx] for idx in sorted(selected))


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；\n])", text)
    return [part.strip() for part in parts if part.strip()]


def _product_aliases(product: str) -> list[str]:
    from pn06.product_dict import PRODUCT_DICT

    return PRODUCT_DICT.get(product, [product])


def _extract_contract(text: str) -> str | None:
    patterns = [
        r"\b([A-Za-z]{1,3}\d{3,4})\b",
        r"([0-9]{2,4})\s*合约",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _contract_key(contract: str | None) -> str:
    return (contract or "").strip().lower().replace("合约", "").replace(" ", "")


def _compact_reason(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]
