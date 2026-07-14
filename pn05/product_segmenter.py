"""
按期货品种切分 cleaned_text。

该模块生成可持久化的正文分段，供规则识别、LLM 精修和前端证据展示共用。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import logging
import re
import time
from typing import Any

from pn06.product_catalog import product_for_symbol, product_key_for_name
from pn06.product_dict import PRODUCT_DICT, ProductMatcher

logger = logging.getLogger(__name__)

__all__ = ["ProductSegment", "segment_text", "segment_article"]


SECTION_TYPE_BY_HEADING = {
    "文档信息": "unknown",
    "核心正文": "core",
    "图文识别正文": "ocr",
    "表格与数据": "table",
    "AI图表解读": "ai",
}

GENERIC_BRACKET_HEADINGS = {
    "观点",
    "观点及策略",
    "观点及操作策略",
    "操作策略",
    "基本面",
    "行情回顾",
    "后市展望",
    "风险提示",
    "宏观",
    "宏观金融",
    "金融期货",
    "商品期货",
    "黑色金属",
    "有色金属",
    "贵金属",
    "能源化工",
    "农产品",
}


@dataclass
class ProductSegment:
    product: str
    product_key: str
    contract: str | None
    section_type: str
    heading: str
    cleaned_text: str
    start_char: int | None
    end_char: int | None
    confidence: float
    raw_product_name: str | None = None
    resolution_method: str = "unknown"
    resolution_confidence: float = 0.0
    segment_index: int = 0
    refined_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Section:
    heading: str
    section_type: str
    text: str
    start_char: int
    end_char: int


@dataclass
class _Block:
    heading: str
    heading_is_explicit: bool
    text: str
    start_char: int
    end_char: int


def segment_article(article_id: int, session: Any) -> list[ProductSegment]:
    """读取文章 cleaned_text，生成并保存品种分段。"""
    from back_end.app.repositories.articles import ArticleRepository

    repo = ArticleRepository(session)
    start = time.monotonic()
    article = repo.get_article_detail(article_id)
    if article is None or article.text is None:
        raise _fail(repo, article_id, "article 或 article_text 不存在")

    cleaned_text = article.text.cleaned_text or ""
    if not cleaned_text.strip():
        raise _fail(repo, article_id, "cleaned_text 为空")

    try:
        from back_end.app.repositories.products import ProductRepository

        product_repo = ProductRepository(session)
        segments = segment_text(cleaned_text, matcher=product_repo.matcher(article_id))
        fingerprint_overrides = product_repo.article_fingerprint_overrides(article_id)
        for segment in segments:
            override_key = fingerprint_overrides.get(segment_fingerprint(segment))
            if not override_key:
                continue
            from pn06.product_catalog import get_product

            definition = get_product(override_key)
            if definition is None:
                continue
            segment.product = definition.display_name
            segment.product_key = definition.product_key
            segment.resolution_method = "manual"
            segment.resolution_confidence = 1.0
            segment.confidence = 1.0
        repo.save_product_segments(article_id, [segment.to_dict() for segment in segments])
        unknown_blocks = [
            {
                "block_fingerprint": segment_fingerprint(segment),
                "segment_index": segment.segment_index,
                "raw_name": segment.raw_product_name or segment.heading,
                "excerpt": segment.cleaned_text[:1000],
                "start_char": segment.start_char,
                "end_char": segment.end_char,
            }
            for segment in segments
            if segment.product == "未知" and segment.section_type != "unknown"
        ]
        product_repo.sync_unknown_resolutions(article_id, unknown_blocks)
        duration_ms = int((time.monotonic() - start) * 1000)
        repo.save_task_log(
            article_id=article_id,
            stage="product_segmenter",
            status="success",
            message=f"segments={len(segments)} products={_product_summary(segments)}",
            duration_ms=duration_ms,
        )
        logger.info("品种分段完成 article_id=%s segments=%s", article_id, len(segments))
        return segments
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        raise _fail(repo, article_id, f"品种分段异常: {exc}", duration_ms=duration_ms) from exc


def segment_text(cleaned_text: str, *, matcher: ProductMatcher | None = None) -> list[ProductSegment]:
    """将 cleaned_text 切分为按品种归属的正文段。"""
    matcher = matcher or ProductMatcher()
    segments: list[ProductSegment] = []
    for section in _split_sections(cleaned_text):
        for block in _split_blocks(section, matcher):
            segments.extend(_segments_from_block(block, section, matcher))

    for index, segment in enumerate(segments):
        segment.segment_index = index
    return [segment for segment in segments if segment.cleaned_text.strip()]


def _split_sections(text: str) -> list[_Section]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    sections: list[_Section] = []
    if not matches:
        return [_Section(heading="", section_type="core", text=text.strip(), start_char=0, end_char=len(text))]

    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        if not content:
            continue
        start_char = content_start + (len(text[content_start:content_end]) - len(text[content_start:content_end].lstrip()))
        end_char = content_end - (len(text[content_start:content_end]) - len(text[content_start:content_end].rstrip()))
        sections.append(
            _Section(
                heading=heading,
                section_type=SECTION_TYPE_BY_HEADING.get(heading, "core"),
                text=content,
                start_char=start_char,
                end_char=end_char,
            )
        )
    return sections


def _split_blocks(section: _Section, matcher: ProductMatcher) -> list[_Block]:
    text = section.text
    boundaries = {0}
    for match in re.finditer(r"【[^】]{1,20}】", text):
        title = match.group(0).strip("【】")
        if title.strip():
            boundaries.add(match.start())

    for match in _iter_product_contract_boundaries(text, matcher):
        boundaries.add(match.start("code"))

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.strip()
        if line and offset > 0 and _starts_product_block(line, matcher):
            boundaries.add(offset + raw_line.find(line))
        offset += len(raw_line)

    ordered = sorted(boundary for boundary in boundaries if 0 <= boundary < len(text))
    blocks: list[_Block] = []
    for index, start in enumerate(ordered):
        end = ordered[index + 1] if index + 1 < len(ordered) else len(text)
        raw = text[start:end]
        stripped = raw.strip()
        if not stripped:
            continue
        trim_left = len(raw) - len(raw.lstrip())
        trim_right = len(raw) - len(raw.rstrip())
        block_start = section.start_char + start + trim_left
        block_end = section.start_char + end - trim_right
        extracted_heading = _extract_heading(stripped, matcher)
        blocks.append(
            _Block(
                heading=extracted_heading or section.heading,
                heading_is_explicit=bool(extracted_heading),
                text=stripped,
                start_char=block_start,
                end_char=block_end,
            )
        )
    return blocks


def _segments_from_block(block: _Block, section: _Section, matcher: ProductMatcher) -> list[ProductSegment]:
    if section.section_type == "unknown":
        return [
            ProductSegment(
                product="未知",
                product_key="",
                contract=None,
                section_type="unknown",
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.1,
                raw_product_name=block.heading,
                resolution_method="unknown",
                resolution_confidence=0.1,
            )
        ]

    heading_product = matcher.resolve_name(block.heading)
    if heading_product is not None:
        return [
            ProductSegment(
                product=heading_product.display_name,
                product_key=heading_product.product_key,
                contract=_extract_contract(block.text),
                section_type=section.section_type,
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.96,
                raw_product_name=block.heading,
                resolution_method="rule",
                resolution_confidence=0.96,
            )
        ]

    heading_counts = matcher.detect_products(block.heading) if block.heading_is_explicit else {}
    if block.heading_is_explicit and not heading_counts and block.heading not in GENERIC_BRACKET_HEADINGS:
        return [
            ProductSegment(
                product="未知",
                product_key="",
                contract=None,
                section_type=section.section_type,
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.1,
                raw_product_name=block.heading,
                resolution_method="unknown",
                resolution_confidence=0.1,
            )
        ]

    product_counts = heading_counts or matcher.detect_products(block.text)
    products = list(product_counts.keys())
    if not products:
        return [
            ProductSegment(
                product="未知",
                product_key="",
                contract=None,
                section_type=section.section_type,
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.1,
                raw_product_name=block.heading,
                resolution_method="unknown",
                resolution_confidence=0.1,
            )
        ]
    if len(products) == 1:
        return [
            ProductSegment(
                product=products[0],
                product_key=product_key_for_name(products[0]),
                contract=_extract_contract(block.text),
                section_type=section.section_type,
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.9,
                raw_product_name=block.heading,
                resolution_method="rule",
                resolution_confidence=0.9,
            )
        ]
    primary_product = _dominant_product(product_counts)
    if primary_product and not _has_explicit_multi_product_markers(block.text, products, matcher):
        return [
            ProductSegment(
                product=primary_product,
                product_key=product_key_for_name(primary_product),
                contract=_extract_contract(block.text),
                section_type=section.section_type,
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.82,
                raw_product_name=block.heading,
                resolution_method="rule",
                resolution_confidence=0.82,
            )
        ]
    return _split_multi_product_block(block, section, products, matcher)


def _split_multi_product_block(
    block: _Block,
    section: _Section,
    products: list[str],
    matcher: ProductMatcher,
) -> list[ProductSegment]:
    sentences = _sentence_spans(block.text)
    segments: list[ProductSegment] = []
    used_texts: set[str] = set()
    for product in products:
        matched = [
            index
            for index, (start, end, sentence) in enumerate(sentences)
            if _mentions_product(sentence, product, matcher)
        ]
        if not matched:
            continue
        selected: set[int] = set()
        for index in matched:
            selected.update(range(max(0, index - 1), min(len(sentences), index + 2)))
        span_start = min(sentences[index][0] for index in selected)
        span_end = max(sentences[index][1] for index in selected)
        local_text = block.text[span_start:span_end].strip()
        if not local_text:
            continue
        used_texts.add(_compact(local_text))
        segments.append(
            ProductSegment(
                product=product,
                product_key=product_key_for_name(product),
                contract=_extract_contract(local_text),
                section_type=section.section_type,
                heading=block.heading,
                cleaned_text=local_text,
                start_char=block.start_char + span_start,
                end_char=block.start_char + span_end,
                confidence=0.72,
                raw_product_name=block.heading,
                resolution_method="rule",
                resolution_confidence=0.72,
            )
        )

    if not segments or (len(used_texts) == 1 and _compact(block.text) in used_texts):
        return [
            ProductSegment(
                product=product,
                product_key=product_key_for_name(product),
                contract=_extract_contract(block.text),
                section_type="mixed",
                heading=block.heading,
                cleaned_text=block.text,
                start_char=block.start_char,
                end_char=block.end_char,
                confidence=0.35,
                raw_product_name=block.heading,
                resolution_method="rule",
                resolution_confidence=0.35,
            )
            for product in products
        ]
    return segments


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    start = 0
    for match in re.finditer(r"[。！？；]", text):
        end = match.end()
        sentence = text[start:end].strip()
        if sentence:
            left_trim = len(text[start:end]) - len(text[start:end].lstrip())
            right_trim = len(text[start:end]) - len(text[start:end].rstrip())
            spans.append((start + left_trim, end - right_trim, sentence))
        start = end
    if start < len(text):
        sentence = text[start:].strip()
        if sentence:
            left_trim = len(text[start:]) - len(text[start:].lstrip())
            right_trim = len(text[start:]) - len(text[start:].rstrip())
            spans.append((start + left_trim, len(text) - right_trim, sentence))
    return spans or [(0, len(text), text)]


def _starts_product_block(line: str, matcher: ProductMatcher) -> bool:
    if line.startswith("#"):
        return _is_product_heading(line.lstrip("#").strip(), matcher)
    if line.startswith("【"):
        match = re.match(r"^【([^】]{1,20})】", line)
        return bool(match and match.group(1).strip())
    return _is_product_prefix(line, matcher)


def _is_product_heading(text: str, matcher: ProductMatcher) -> bool:
    cleaned = re.sub(r"^[#\s]+", "", text).strip("【】 ：:")
    if not cleaned or cleaned in GENERIC_BRACKET_HEADINGS:
        return False
    return bool(matcher.detect_products(cleaned))


def _is_product_prefix(line: str, matcher: ProductMatcher) -> bool:
    prefix = line[:40].strip()
    if _product_contract_prefix_definition(prefix, matcher) is not None:
        return True
    products = matcher.detect_products(prefix)
    for product in products:
        aliases = PRODUCT_DICT.get(product, [product])
        for alias in [product, *aliases]:
            if re.match(rf"^{re.escape(alias)}(?:\s*[：:]|\s|$)", prefix, flags=re.IGNORECASE):
                return True
    return False


def _mentions_product(text: str, product: str, matcher: ProductMatcher) -> bool:
    return product in matcher.detect_products(text)


def _dominant_product(product_counts: dict[str, int]) -> str | None:
    if len(product_counts) < 2:
        return None
    ordered = list(product_counts.items())
    first_product, first_count = ordered[0]
    _second_product, second_count = ordered[1]
    if first_count >= 2 and first_count > second_count:
        return first_product
    return None


def _has_explicit_multi_product_markers(text: str, products: list[str], matcher: ProductMatcher) -> bool:
    marker_count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _starts_product_block(stripped, matcher):
            marker_count += 1
    marker_count += sum(
        1
        for match in re.finditer(r"【([^】]{1,20})】", text)
        if _is_product_heading(match.group(1), matcher)
    )
    if marker_count >= 2:
        return True
    sentence_products = [
        product
        for product in products
        if any(_mentions_product(sentence, product, matcher) for *_bounds, sentence in _sentence_spans(text))
    ]
    return len(set(sentence_products)) >= 2 and not _dominant_product(matcher.detect_products(text))


def _extract_heading(text: str, matcher: ProductMatcher) -> str:
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    if first_line.startswith("#"):
        return first_line.lstrip("#").strip()
    bracket = re.match(r"^【([^】]{1,20})】", first_line)
    if bracket and bracket.group(1).strip():
        return bracket.group(1)
    contract_definition = _product_contract_prefix_definition(first_line[:80], matcher)
    if contract_definition is not None:
        return contract_definition.display_name
    if _is_product_prefix(first_line, matcher):
        return re.split(r"[：:]", first_line, maxsplit=1)[0].strip()[:80]
    return ""


def _iter_product_contract_boundaries(text: str, matcher: ProductMatcher):
    pattern = re.compile(r"(?P<prefix>^|[\n。！？；;])\s*(?P<code>[A-Za-z]{1,5})(?P<contract>\d{2,4})\s*合约", re.IGNORECASE)
    for match in pattern.finditer(text):
        if _product_definition_for_contract_code(match.group("code"), matcher) is not None:
            yield match


def _product_contract_prefix_definition(line: str, matcher: ProductMatcher):
    match = re.match(r"^\s*(?P<code>[A-Za-z]{1,5})(?P<contract>\d{2,4})\s*合约", line, flags=re.IGNORECASE)
    if not match:
        return None
    return _product_definition_for_contract_code(match.group("code"), matcher)


def _product_definition_for_contract_code(code: str, matcher: ProductMatcher):
    definition = product_for_symbol(code)
    if definition is not None:
        return definition
    return matcher.resolve_name(code)


def _extract_contract(text: str) -> str | None:
    for match in re.finditer(r"\b([A-Za-z]{1,3})(\d{2,4})(?=\s*合约|[^A-Za-z0-9]|$)", text):
        if product_for_symbol(match.group(1)) is not None:
            return match.group(0)
    match = re.search(r"([0-9]{2,4})\s*合约", text)
    if match:
        return match.group(1)
    return None


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def segment_fingerprint(segment: ProductSegment | Any) -> str:
    raw = "|".join(
        (
            str(getattr(segment, "heading", "") or ""),
            str(getattr(segment, "start_char", "") or ""),
            str(getattr(segment, "end_char", "") or ""),
            _compact(str(getattr(segment, "cleaned_text", "") or ""))[:500],
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _product_summary(segments: list[ProductSegment]) -> str:
    products = [segment.product for segment in segments if segment.product != "未知"]
    if not products:
        return "none"
    return ",".join(dict.fromkeys(products))


def _fail(repo: Any, article_id: int, msg: str, duration_ms: int | None = None) -> ValueError:
    try:
        repo.mark_failed(article_id=article_id, stage="product_segmenter", message=msg, duration_ms=duration_ms)
    except Exception as exc:
        logger.error("写入品种分段失败日志异常: %s", exc)
    return ValueError(msg)
