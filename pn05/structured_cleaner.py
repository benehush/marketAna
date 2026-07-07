"""
pn05 结构化清洗器。

识别 pn04 输出的轻量 Markdown raw_text，并按正文、表格、OCR、AI 解读
分别清洗。输出仍是普通 Markdown 文本，便于 pn06 规则扫描和 pn07 LLM 推理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from pn05.models import CleanConfig
from pn05.noise_rules import filter_noise_lines, filter_noise_regex
from pn05.normalizer import (
    detect_and_clean_encoding,
    normalize_fullwidth,
    normalize_whitespace,
    remove_html_residue,
)

__all__ = ["StructuredCleanStats", "clean_text"]


@dataclass
class StructuredCleanStats:
    """结构化清洗过程中的补充统计。"""

    noise_lines_removed: int = 0
    numeric_blocks_removed: int = 0
    low_density_removed: int = 0


@dataclass
class _DocumentSections:
    title: str = ""
    source_file: str = ""
    parser_type: str = ""
    body: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    image_ocr: list[str] = field(default_factory=list)
    ai: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


_SECTION_TO_FIELD = {
    "正文文本": "body",
    "表格数据": "tables",
    "图片OCR文本": "image_ocr",
    "AI图表解读": "ai",
}

_SEMANTIC_HINTS = (
    "观点", "逻辑", "建议", "操作", "策略", "展望", "预测", "预计", "预期",
    "价格", "中枢", "上涨", "下跌", "上行", "下行", "偏强", "偏弱", "震荡",
    "库存", "需求", "供应", "成本", "利润", "基差", "现货", "期货", "产业链",
    "利多", "利空", "支撑", "压力", "风险", "关注",
)

_NAVIGATION_ONLY_LINES = {
    "晨报", "日报", "周报", "月报", "年报",
    "农产品", "能源化工", "有色金属", "黑色金属", "金融期货",
    "商品期货", "股指期货", "国债期货", "交易策略",
}


def clean_text(text: str, config: CleanConfig) -> tuple[str, StructuredCleanStats]:
    """清洗 raw_text，优先按 pn04 模板输出结构化 cleaned_text。"""
    stats = StructuredCleanStats()
    text = _normalize_base(text, config)

    doc = _parse_document_sections(text)
    if config.structured_output and _looks_like_pn04_document(doc):
        cleaned = _clean_structured_document(doc, config, stats)
    else:
        cleaned = _clean_plain_text(text, config, stats)

    cleaned = _finalize_text(cleaned, config)
    return cleaned, stats


def _normalize_base(text: str, config: CleanConfig) -> str:
    text = detect_and_clean_encoding(text)
    if config.remove_html_residue:
        text = remove_html_residue(text)
    if config.normalize_whitespace:
        text = normalize_whitespace(text)
    if config.normalize_fullwidth:
        text = normalize_fullwidth(text)
    return text


def _parse_document_sections(text: str) -> _DocumentSections:
    doc = _DocumentSections()
    current_field = "other"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        if content:
            getattr(doc, current_field).append(content)
        buffer = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            buffer.append("")
            continue

        if line.startswith("# ") and not doc.title:
            doc.title = line[2:].strip()
            continue
        if line.startswith("来源文件:"):
            doc.source_file = line.split(":", 1)[1].strip()
            continue
        if line.startswith("解析器:"):
            doc.parser_type = line.split(":", 1)[1].strip()
            continue
        if line.startswith("## "):
            flush()
            section_name = line[3:].split(":", 1)[0].strip()
            current_field = _SECTION_TO_FIELD.get(section_name, "other")
            continue

        buffer.append(line)

    flush()
    return doc


def _looks_like_pn04_document(doc: _DocumentSections) -> bool:
    return bool(doc.title or doc.source_file or doc.parser_type) and bool(
        doc.body or doc.tables or doc.image_ocr or doc.ai or doc.other
    )


def _clean_structured_document(
    doc: _DocumentSections,
    config: CleanConfig,
    stats: StructuredCleanStats,
) -> str:
    title = _clean_title(doc.title)
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")

    if config.preserve_source_header and (doc.source_file or doc.parser_type):
        info_lines = []
        if doc.source_file:
            info_lines.append(f"来源文件: {doc.source_file}")
        if doc.parser_type:
            info_lines.append(f"解析器: {doc.parser_type}")
        parts.extend(["## 文档信息", "\n".join(info_lines)])

    body = _clean_content_blocks(doc.body + doc.other, config, stats, mode="body")
    if body:
        parts.extend(["## 核心正文", body])

    tables = _clean_content_blocks(doc.tables, config, stats, mode="table")
    if tables:
        if config.keep_markdown_tables and not tables.startswith("### 表格"):
            tables = "### 表格: 价格/库存/基差数据\n" + tables
        parts.extend(["## 表格与数据", tables])

    ocr = _clean_content_blocks(doc.image_ocr, config, stats, mode="ocr")
    if ocr:
        parts.extend(["## 图文识别正文", ocr])

    ai_text = _clean_content_blocks(doc.ai, config, stats, mode="ai")
    if ai_text:
        parts.extend(["## AI图表解读", ai_text])

    return "\n\n".join(parts)


def _clean_plain_text(
    text: str,
    config: CleanConfig,
    stats: StructuredCleanStats,
) -> str:
    text, regex_removed = filter_noise_regex(text)
    if regex_removed:
        stats.noise_lines_removed += 1
    return _clean_content_blocks([text], config, stats, mode="body")


def _clean_content_blocks(
    blocks: list[str],
    config: CleanConfig,
    stats: StructuredCleanStats,
    *,
    mode: str,
) -> str:
    cleaned_blocks: list[str] = []
    for block in blocks:
        text, regex_removed = filter_noise_regex(block)
        if regex_removed:
            stats.noise_lines_removed += 1

        lines, noise_removed = filter_noise_lines(text.splitlines())
        stats.noise_lines_removed += noise_removed

        if mode == "table":
            lines = _clean_table_lines(lines, config, stats)
        else:
            lines = _clean_semantic_lines(lines, config, stats, mode=mode)

        compact = _compact_lines(lines)
        if compact:
            cleaned_blocks.append(compact)
    return "\n\n".join(cleaned_blocks).strip()


def _clean_table_lines(
    lines: list[str],
    config: CleanConfig,
    stats: StructuredCleanStats,
) -> list[str]:
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if config.keep_markdown_tables and _is_markdown_separator(stripped):
            kept.append(stripped)
            continue
        if _is_numeric_dominant_noise(stripped, config, mode="table"):
            stats.numeric_blocks_removed += 1
            continue
        if _is_low_value_ocr_line(stripped, config, mode="table"):
            stats.low_density_removed += len(line)
            continue
        kept.append(stripped)
    return kept


def _clean_semantic_lines(
    lines: list[str],
    config: CleanConfig,
    stats: StructuredCleanStats,
    *,
    mode: str,
) -> list[str]:
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if stripped.startswith("[图片分片") and stripped.endswith("]"):
            stats.noise_lines_removed += 1
            continue
        if _is_navigation_only_line(stripped):
            stats.noise_lines_removed += 1
            continue
        if config.drop_numeric_dominant_blocks and _is_numeric_dominant_noise(stripped, config, mode=mode):
            stats.numeric_blocks_removed += 1
            continue
        if _is_low_value_ocr_line(stripped, config, mode=mode):
            stats.low_density_removed += len(line)
            continue
        kept.append(_repair_ocr_line(stripped))
    return _drop_numeric_runs(kept, config, stats)


def _drop_numeric_runs(
    lines: list[str],
    config: CleanConfig,
    stats: StructuredCleanStats,
) -> list[str]:
    """删除连续坐标轴/刻度行，避免单行漏网形成大段数字噪声。"""
    result: list[str] = []
    run: list[str] = []

    def flush_run() -> None:
        nonlocal run
        if len(run) >= 2:
            stats.numeric_blocks_removed += len(run)
        else:
            result.extend(run)
        run = []

    for line in lines:
        if line and _is_chart_axis_noise(line, config):
            run.append(line)
        else:
            flush_run()
            result.append(line)
    flush_run()
    return result


def _is_numeric_dominant_noise(line: str, config: CleanConfig, *, mode: str) -> bool:
    if not config.drop_numeric_dominant_blocks:
        return False
    if _has_semantic_signal(line):
        return False

    cjk = _count_cjk(line)
    if mode == "table" and line.startswith("|") and cjk > 0:
        return False
    if cjk > config.numeric_block_max_cjk_chars:
        return False

    compact = line.replace(" ", "")
    if not compact:
        return True

    digits = len(re.findall(r"\d", compact))
    ratio = digits / max(len(compact), 1)
    date_count = len(re.findall(r"\b\d{1,2}[-/.]\d{1,2}\b", line))
    numeric_tokens = len(re.findall(r"[-+]?\d[\d,.]*", line))

    if date_count >= config.chart_axis_date_count:
        return True
    if ratio >= config.numeric_block_digit_ratio and numeric_tokens >= 2:
        return True
    if mode == "ocr" and ratio >= 0.25 and cjk <= 2 and numeric_tokens >= 3:
        return True
    if re.fullmatch(r"[\d\s,.\-+/%()]+", line):
        return True
    return False


def _is_chart_axis_noise(line: str, config: CleanConfig) -> bool:
    if _has_semantic_signal(line):
        return False
    date_count = len(re.findall(r"\b\d{1,2}[-/.]\d{1,2}\b", line))
    if date_count >= 3:
        return True
    if len(re.findall(r"\b\d{4,5}\b", line)) >= 4 and _count_cjk(line) <= 2:
        return True
    return _is_numeric_dominant_noise(line, config, mode="ocr")


def _is_low_value_ocr_line(line: str, config: CleanConfig, *, mode: str) -> bool:
    if line.startswith("#") or line.startswith("|"):
        return False
    if _has_semantic_signal(line):
        return False

    cjk = _count_cjk(line)
    clean_len = len(re.sub(r"\s+", "", line))
    alpha = len(re.findall(r"[A-Za-z]", line))

    if clean_len < config.min_semantic_line_chars and cjk == 0:
        return True
    if mode in {"ocr", "body"} and cjk == 0 and alpha >= 3 and clean_len <= 24:
        return True
    if mode == "ocr" and cjk <= 1 and _symbol_ratio(line) > 0.45:
        return True
    return False


def _clean_title(title: str) -> str:
    title = title.strip().lstrip("#").strip()
    return title if title and not _is_noise_title(title) else ""


def _is_noise_title(title: str) -> bool:
    return title in {"解析文档", "浙商期货官网"} or "官网" in title


def _has_semantic_signal(line: str) -> bool:
    if any(hint in line for hint in _SEMANTIC_HINTS):
        return True
    return _count_cjk(line) >= 7


def _is_navigation_only_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if compact in _NAVIGATION_ONLY_LINES:
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{1,12}(日报|周报|月报|年报)\d{6,8}", compact):
        return True
    if re.fullmatch(r"【?[\u4e00-\u9fffA-Za-z]{1,12}(日报|周报|月报|年报)\d{6,8}】?", compact):
        return True
    return False


def _repair_ocr_line(line: str) -> str:
    line = re.sub(r"\s{2,}", " ", line)
    line = re.sub(r"([一-鿿])\s+([一-鿿])", r"\1\2", line)
    return line.strip()


def _compact_lines(lines: list[str]) -> str:
    non_empty = [line for line in lines if line.strip()]
    if lines and len(non_empty) / len(lines) < 0.7:
        lines = non_empty
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _finalize_text(text: str, config: CleanConfig) -> str:
    text = normalize_whitespace(text)
    if config.normalize_fullwidth:
        text = normalize_fullwidth(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _count_cjk(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _symbol_ratio(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return 1.0
    symbols = len(re.findall(r"[^A-Za-z0-9一-鿿]", compact))
    return symbols / len(compact)


def _is_markdown_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line))
