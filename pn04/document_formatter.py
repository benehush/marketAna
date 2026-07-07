"""
pn04 统一 raw_text 输出格式。

解析器仍返回普通字符串，但在字符串中保留来源、解析器、正文、
表格、图片 OCR 和可选 AI 解读的段落标记，方便 pn05 后续清洗。
"""

from __future__ import annotations

from pathlib import Path


def build_document_text(
    *,
    title: str | None,
    source_file: str,
    parser_type: str,
    body_text: str = "",
    table_text: str = "",
    image_ocr_sections: list[tuple[str, str]] | None = None,
    ai_sections: list[tuple[str, str]] | None = None,
    max_text_length: int = 500_000,
) -> str:
    """构建面向下游清洗模块的统一原始文本。"""
    display_title = _clean_line(title) or Path(source_file).name or "解析文档"
    sections: list[str] = [
        f"# {display_title}",
        f"来源文件: {source_file}",
        f"解析器: {parser_type}",
    ]

    if body_text.strip():
        sections.extend(["## 正文文本", body_text.strip()])

    if table_text.strip():
        sections.extend(["## 表格数据", table_text.strip()])

    for image_path, ocr_text in image_ocr_sections or []:
        if ocr_text.strip():
            sections.extend([f"## 图片OCR文本: {image_path}", ocr_text.strip()])

    for image_path, ai_text in ai_sections or []:
        if ai_text.strip():
            sections.extend([f"## AI图表解读: {image_path}", ai_text.strip()])

    text = "\n\n".join(sections).strip()
    if len(text) > max_text_length:
        text = text[:max_text_length] + f"\n\n[文本过长，已截断，原长度: {len(text)} 字符]"
    return text


def _clean_line(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())
