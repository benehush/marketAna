"""
pn04 PDF 解析器

使用 PyMuPDF (fitz) 按页读取 PDF 文本，保留页码标记和段落顺序。
对扫描件 PDF（无文本层）可降级到 OCR 处理。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from pn04.document_formatter import build_document_text
from pn04.exceptions import EmptyContentError, FileReadError, FileNotFoundError_
from pn04.models import ParseConfig, ParseResult, ParserType
from pn04.table_utils import pdf_table_to_markdown

logger = logging.getLogger(__name__)


class PdfParser:
    """PDF 文件解析器。

    使用 PyMuPDF 逐页提取文本，保留页码标记和段落顺序。
    对于无文本层的扫描页，可选降级到 OCR。

    Usage:
        parser = PdfParser(config=ParseConfig())
        result = parser.parse("/path/to/report.pdf")
    """

    def __init__(self, config: ParseConfig | None = None) -> None:
        self.config = config or ParseConfig()

    def parse(self, file_path: str) -> ParseResult:
        """
        解析 PDF 文件并返回纯文本。

        Args:
            file_path: PDF 文件的本地路径

        Returns:
            ParseResult: 包含解析文本和元数据

        Raises:
            FileNotFoundError_: 文件不存在
            FileReadError: 文件读取失败
            EmptyContentError: 解析结果为空
        """
        self._validate_file(file_path)
        try:
            import fitz  # pymupdf
        except ImportError:
            raise ImportError(
                "pymupdf 未安装，请执行: pip install pymupdf"
            )

        metadata: dict[str, Any] = {
            "file_path": file_path,
            "total_pages": 0,
            "text_pages": 0,
            "ocr_pages": 0,
            "tables_found": 0,
        }

        all_pages: list[str] = []
        table_texts: list[str] = []

        try:
            doc = fitz.open(file_path)
            metadata["total_pages"] = len(doc)

            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = self._extract_page_text(page, page_num + 1)

                if page_text.strip():
                    # 提取表格
                    if self.config.extract_tables:
                        tables = self._extract_page_tables(page)
                        for tbl in tables:
                            md_table = pdf_table_to_markdown(
                                tbl,
                                add_description=self.config.table_add_description,
                            )
                            if md_table.strip():
                                table_texts.append(f"### Page {page_num} 表格\n{md_table}")

                    all_pages.append(page_text)
                    metadata["text_pages"] += 1
                elif self.config.pdf_ocr_fallback:
                    # 扫描页：降级到 OCR
                    ocr_text = self._ocr_page(page, page_num + 1)
                    if ocr_text.strip():
                        all_pages.append(ocr_text)
                        metadata["ocr_pages"] += 1

            doc.close()

            metadata["tables_found"] = len(table_texts)
            body_text = "\n\n".join(all_pages)
            table_text = "\n\n".join(table_texts)
            raw_text = build_document_text(
                title=os.path.basename(file_path),
                source_file=file_path,
                parser_type=ParserType.PDF.value,
                body_text=body_text,
                table_text=table_text,
                max_text_length=self.config.max_text_length,
            )

            if not raw_text.strip():
                raise EmptyContentError(
                    parser_type=ParserType.PDF.value,
                    file_path=file_path,
                )

            # 截断处理
            if len(raw_text) > self.config.max_text_length:
                raw_text = (
                    raw_text[: self.config.max_text_length]
                    + f"\n\n[文本过长，已截断，原长度: {len(raw_text)} 字符]"
                )

            return ParseResult(
                parser_type=ParserType.PDF,
                raw_text=raw_text,
                metadata=metadata,
            )

        except EmptyContentError:
            raise
        except Exception as exc:
            raise FileReadError(file_path, reason=str(exc)) from exc

    # ---- 内部方法 ----

    @staticmethod
    def _validate_file(file_path: str) -> None:
        """验证文件存在且可读。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError_(file_path)
        if not os.path.isfile(file_path):
            raise FileReadError(file_path, reason="路径不是文件")

    def _extract_page_text(self, page: Any, page_num: int) -> str:
        """
        从单页 PDF 提取文本，添加页码标记。

        Args:
            page: PyMuPDF Page 对象
            page_num: 页码（从 1 开始）

        Returns:
            带页码标记的页面文本
        """
        try:
            text = page.get_text("text", sort=True)  # type: ignore[arg-type]
        except Exception:
            text = page.get_text()

        if not text or len(text.strip()) < self.config.pdf_min_chars_per_page:
            return ""

        # 页码标记
        header = f"\n## Page {page_num}\n"
        return header + text.strip()

    def _extract_page_tables(self, page: Any) -> list[list[list[str]]]:
        """
        提取 PDF 页面中的表格。

        使用 PyMuPDF 的 table 检测功能。

        Returns:
            表格列表，每个表格是二维字符串数组
        """
        tables: list[list[list[str]]] = []
        try:
            found = page.find_tables()
            if found and found.tables:
                for table in found.tables:
                    cells: list[list[str]] = []
                    for row in table.extract():
                        row_cells = [str(cell) if cell is not None else "" for cell in row]
                        cells.append(row_cells)
                    if cells:
                        tables.append(cells)
        except Exception:
            # 表格检测失败不是致命错误
            pass
        return tables

    def _ocr_page(self, page: Any, page_num: int) -> str:
        """
        对 PDF 页面执行 OCR（扫描件降级处理）。

        将页面渲染为图片后调用 OCR 引擎。

        Args:
            page: PyMuPDF Page 对象
            page_num: 页码

        Returns:
            OCR 识别的文本
        """
        try:
            # 将页面渲染为高分辨率图片
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")

            from pn04.image_parser import ImageParser

            img_parser = ImageParser(config=self.config)
            ocr_text = img_parser.ocr_from_bytes(img_bytes)

            if ocr_text.strip():
                return f"\n## Page {page_num} (OCR)\n" + ocr_text.strip()
            return ""
        except Exception as exc:
            logger.warning(f"PDF 第 {page_num} 页 OCR 失败: {exc}")
            return ""
