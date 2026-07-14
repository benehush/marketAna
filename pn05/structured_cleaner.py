"""
pn05 结构化清洗器。

识别 pn04 输出的轻量 Markdown raw_text，并按正文、表格、OCR、AI 解读
分别清洗。输出仍是普通 Markdown 文本，便于 pn06 规则扫描和 pn07 LLM 推理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable

from pn05.models import CleanConfig
from pn05.noise_rules import filter_noise_lines, filter_noise_regex
from pn05.normalizer import (
    detect_and_clean_encoding,
    normalize_fullwidth,
    normalize_whitespace,
    remove_html_residue,
)

ProgressCallback = Callable[[str], None]

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
    "利多", "利空", "支撑", "压力", "风险", "关注", "产能", "装置", "负荷",
    "原油", "开工率", "投产",
)

_CORE_SEMANTIC_HINTS = (
    "观点", "逻辑", "建议", "策略", "预计", "预期", "价格中枢", "震荡下行",
    "震荡上行", "偏强", "偏弱", "看涨", "看跌", "产能", "装置", "投产",
    "负荷", "需求", "供应", "库存", "成本", "原油", "基差", "压力",
)

_JUDGEMENT_HINTS = (
    "观点", "逻辑", "建议", "预计", "预期", "有望", "看涨", "看跌", "偏强",
    "偏弱", "上行", "下行", "上涨", "下跌", "回落", "改善", "承压", "支撑",
    "维持", "关注", "风险", "震荡",
)

_NAVIGATION_ONLY_LINES = {
    "晨报", "日报", "周报", "月报", "年报",
    "农产品", "能源化工", "有色金属", "黑色金属", "金融期货",
    "商品期货", "股指期货", "国债期货", "交易策略",
}


def clean_text(
    text: str,
    config: CleanConfig,
    *,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str, StructuredCleanStats]:
    """清洗 raw_text，优先按 pn04 模板输出结构化 cleaned_text。"""
    stats = StructuredCleanStats()
    _emit_progress(progress_callback, "基础规范化")
    text = _normalize_base(text, config)

    _emit_progress(progress_callback, "结构解析")
    doc = _parse_document_sections(text)
    if config.structured_output and _looks_like_pn04_document(doc):
        _emit_progress(progress_callback, "结构化去噪")
        cleaned = _clean_structured_document(doc, config, stats)
    else:
        _emit_progress(progress_callback, "文本去噪")
        cleaned = _clean_plain_text(text, config, stats)

    _emit_progress(progress_callback, "格式整理")
    cleaned = _finalize_text(cleaned, config)
    return cleaned, stats


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


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
            info_lines.append(f"来源文件: {_source_display_name(doc.source_file)}")
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
    skipping_disclaimer = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            skipping_disclaimer = False
            kept.append("")
            continue
        if config.drop_disclaimer_blocks and mode in {"body", "ocr"}:
            if skipping_disclaimer and _is_disclaimer_block_continuation(stripped):
                stats.noise_lines_removed += 1
                continue
            skipping_disclaimer = False
            if _is_disclaimer_block_start(stripped):
                skipping_disclaimer = True
                stats.noise_lines_removed += 1
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
        repaired = _repair_ocr_line(stripped)
        if _is_strict_semantic_noise(repaired, config, mode=mode):
            stats.low_density_removed += len(line)
            continue
        kept.append(repaired)
    kept = _drop_numeric_runs(kept, config, stats)
    if mode == "ocr" and config.semantic_line_filter:
        kept = _prioritize_ocr_semantic_lines(kept)
    return kept


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


def _is_strict_semantic_noise(line: str, config: CleanConfig, *, mode: str) -> bool:
    if not config.semantic_line_filter:
        return False
    if mode not in {"ocr", "body"}:
        return False
    if not config.strict_ocr_noise_filter and mode == "ocr":
        return False
    if line.startswith("#") or line.startswith("|"):
        return False

    if _is_residual_disclaimer_noise(line):
        return True
    if _is_company_footer_noise(line):
        return True
    if _is_data_source_noise(line):
        return True
    if _is_chart_title_noise(line):
        return True
    if _is_garbled_alpha_noise(line, config):
        return True
    if config.drop_pdf_fragment_lines and _is_pdf_fragment_line(line, config):
        return True
    if _is_low_value_table_fragment(line):
        return True

    return False


def _is_disclaimer_block_start(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    patterns = (
        "期货有限公司是经中国证监会批准",
        "本刊所有信息均建立在可靠",
        "不构成买卖建议",
        "不构成任何投资建议",
        "未经书面许可",
        "研究报告不代表协会观点",
        "粤海街道",
        "金融大厦",
        "资产管理、期货交易咨询等业务资格",
        "本报告并不提供量身定制的交易建议",
        "版权声明",
        "复制本刊任何内容皆属违反版权法行为",
        "独立评估特定的交易",
        "专业财务顾问",
    )
    if any(pattern in compact for pattern in patterns):
        return True
    if compact.startswith("的观点") and "概不负责" in compact:
        return True
    if compact.startswith("书面许可") and "复制" in compact:
        return True
    if compact.startswith("经许可") and "损失赔偿" in compact:
        return True
    if re.search(r"[\u4e00-\u9fff]{2,16}期货有限公司是经", compact):
        return True
    return False


def _is_disclaimer_block_continuation(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if _is_disclaimer_block_start(line):
        return True
    patterns = (
        "商品期货经纪", "金融期货经纪", "资产管理", "期货交易咨询",
        "我们力求", "精确的数据", "客观的分析", "概不负责",
        "量身定制的交易建议", "财务状况及目标", "研究团队建议",
        "独立评估特定的交易", "专业财务顾问", "交易者自身的状况",
        "文中所提及", "仅供参考", "电子机械影印录音", "复制传播",
        "存储于任何检索系统", "违反版权法", "损失赔偿",
    )
    return any(pattern in compact for pattern in patterns)


def _is_residual_disclaimer_noise(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    patterns = (
        "会计或税务", "最终操作建议", "任何担保", "本报告中使用",
        "所有在本报告", "免责条款", "免责声明", "不构成投资",
        "未经本公司允许", "商标服务标识", "准确性和完整性",
        "不构成买卖建议", "不构成任何投资建议", "未经书面许可",
        "研究报告不代表协会观点", "本刊所有信息均建立在可靠",
        "资产管理、期货交易咨询等业务资格", "本报告并不提供量身定制",
        "复制本刊任何内容皆属违反版权法行为", "独立评估特定的交易",
        "专业财务顾问",
    )
    return any(pattern in compact for pattern in patterns) or (
        compact.startswith("的观点") and "概不负责" in compact
    )


def _is_company_footer_noise(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if compact in {"浙商期货有限公司", "请务必阅读正文之后的免责条款和声明"}:
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{2,12}期货有限公司", compact):
        return True
    return False


def _is_data_source_noise(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    source_tokens = ("数据来源", "数据源", "数据未源", "数据床源", "数据订源", "更新频率")
    if any(token in compact for token in source_tokens):
        return True
    if re.search(r"\b(WIND|FIND|BIS|BRE|SUE|Bae|SORE|SG\d*)\b", line, flags=re.IGNORECASE):
        return not _has_judgement_signal(line)
    return False


def _is_chart_title_noise(line: str) -> bool:
    if _has_judgement_signal(line):
        return False
    compact = re.sub(r"\s+", "", line)
    title_compact = re.sub(r"[、，,。.\s]+", "", line)
    if title_compact in {"货价格及价差", "基差及盘面价差", "上游利润及开工率", "下游利润及开工率", "持仓成交与仓单博"}:
        return True
    has_date = bool(re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", line))
    chart_terms = (
        "价格", "价差", "利润", "开工率", "持仓量", "成交量", "仓单", "基差",
        "日产量", "损失量", "区域价差",
    )
    if has_date and any(term in compact for term in chart_terms):
        return True
    if len(re.findall(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", line)) >= 2:
        return True
    return False


def _is_garbled_alpha_noise(line: str, config: CleanConfig) -> bool:
    if _has_core_semantic_signal(line):
        return False
    compact = re.sub(r"\s+", "", line)
    if not compact:
        return True
    alpha = len(re.findall(r"[A-Za-z]", compact))
    cjk = _count_cjk(compact)
    ratio = alpha / max(len(compact), 1)
    if alpha >= 8 and ratio >= config.max_ocr_noise_alpha_ratio and cjk < config.min_ocr_semantic_cjk_chars:
        return True
    if alpha >= 12 and cjk <= 2:
        return True
    return False


def _is_low_value_table_fragment(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if compact in {"[日报", "日报", "参与角色行为导向情形导向"}:
        return True
    table_tokens = (
        "库存管理", "库序管理", "库存优育", "有网管理", "终端宕户", "原料库存",
        "套保比例", "入场价格", "相关场外产品", "期权增强收益", "期祝增强收益",
        "控制采购成本", "锁定志出价格", "卖出看涨期权", "预防价格下跌",
        "款要PE原料", "焊f工生", "WEE",
    )
    if any(token in compact for token in table_tokens):
        return True
    if _has_judgement_signal(line):
        return False
    if re.fullmatch(r"[A-Za-z|、。.,:：;；()（）_\-+=/\\\d\u4e00-\u9fff]{1,8}", compact):
        return not _has_core_semantic_signal(compact)
    if re.match(r"^\d+\s+\d+、", line) and len(re.findall(r"[-+]?\d[\d,.]*", line)) >= 4:
        return True
    if len(re.findall(r"[-+]?\d[\d,.]*", line)) >= 4 and not _has_core_semantic_signal(line):
        return True
    return False


def _is_pdf_fragment_line(line: str, config: CleanConfig) -> bool:
    if _has_judgement_signal(line):
        return False
    compact = re.sub(r"\s+", "", line)
    cjk = _count_cjk(compact)
    numbers = len(re.findall(r"[-+]?\d[\d,.]*", line))

    if re.match(r"^(吨|元|手|面|方面|仓|单|量)[,，.。;；\s]", line) and numbers >= 1:
        return True
    if re.match(r"^(吨|元|手)[,，.。;；]?", compact) and cjk <= config.pdf_fragment_min_cjk_chars and numbers >= 1:
        return True
    if compact.startswith(("当日注册仓", "注册仓", "变化至", "环比变化至")):
        return True
    if re.search(r"环比变化至\d", compact):
        return True
    if re.search(r"(主力合约持仓量|总持仓|持仓量).*环比减少\d", compact) and cjk <= 18:
        return True
    if numbers >= 3 and cjk <= config.pdf_fragment_min_cjk_chars:
        fragment_terms = ("环比", "持仓", "注册仓", "合约", "现货市场", "收盘价", "价格")
        return any(term in compact for term in fragment_terms)
    return False


def _prioritize_ocr_semantic_lines(lines: list[str]) -> list[str]:
    priority: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = re.sub(r"\s+", "", line)
        if not key:
            rest.append(line)
            continue
        target = priority if _is_priority_ocr_line(line) else rest
        if key in seen:
            continue
        seen.add(key)
        target.append(line)
    return priority + rest


def _is_priority_ocr_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return bool(re.match(r"^[\[\]【】“”\"'汪\s]*(观点|逻辑|建议|策略)[:：]", compact))


def _clean_title(title: str) -> str:
    title = title.strip().lstrip("#").strip()
    return title if title and not _is_noise_title(title) else ""


def _source_display_name(source_file: str) -> str:
    """仅保留文件名，避免路径中的英文片段污染品种识别。"""
    return re.split(r"[/\\]", source_file.strip())[-1] or source_file.strip()


def _is_noise_title(title: str) -> bool:
    return title in {"解析文档", "浙商期货官网"} or "官网" in title


def _has_semantic_signal(line: str) -> bool:
    if any(hint in line for hint in _SEMANTIC_HINTS):
        return True
    return _count_cjk(line) >= 7


def _has_core_semantic_signal(line: str) -> bool:
    if any(hint in line for hint in _CORE_SEMANTIC_HINTS):
        return True
    return _count_cjk(line) >= 12 and _has_judgement_signal(line)


def _has_judgement_signal(line: str) -> bool:
    return any(hint in line for hint in _JUDGEMENT_HINTS)


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
    line = re.sub(r"^[\[\]【】“”\"'汪\s]+(?=(观点|逻辑|建议|策略)[:：])", "", line)
    line = line.replace("年未", "年末")
    line = line.replace("装直", "装置")
    line = line.replace("上且", "且")
    line = line.replace("产员穿全年", "产能压力贯穿全年")
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
