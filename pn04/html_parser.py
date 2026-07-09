"""
pn04 HTML 解析器

使用 BeautifulSoup 解析 HTML 文件，移除脚本、样式、广告和导航噪声，
提取正文文本，并将 <table> 转换为 Markdown 格式。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from pn04.ai_enhancer import ParserAIEnhancer
from pn04.document_formatter import build_document_text
from pn04.exceptions import EmptyContentError, FileReadError, FileNotFoundError_
from pn04.image_parser import ImageParser
from pn04.models import ParseConfig, ParseResult, ParserType
from pn04.table_utils import extract_table_text, html_table_to_markdown

logger = logging.getLogger(__name__)


# 需移除的标签
_REMOVE_TAGS = [
    "script", "style", "noscript", "iframe",
    "nav", "footer", "header", "aside",
    "form", "input", "button", "select",
]

# 需移除的 class/id 关键词（广告、导航、页脚等）
_REMOVE_SELECTORS = [
    '[class*="ad"]', '[id*="ad"]',
    '[class*="banner"]', '[id*="banner"]',
    '[class*="nav"]', '[id*="nav"]',
    '[class*="menu"]', '[id*="menu"]',
    '[class*="footer"]', '[id*="footer"]',
    '[class*="sidebar"]', '[id*="sidebar"]',
    '[class*="widget"]', '[id*="widget"]',
    '[class*="comment"]', '[id*="comment"]',
    '[class*="share"]', '[id*="share"]',
    '[class*="social"]', '[id*="social"]',
    '[class*="popup"]', '[id*="popup"]',
    '[class*="cookie"]', '[id*="cookie"]',
    '[class*="disclaimer"]', '[id*="disclaimer"]',
    '[role="navigation"]',
    '[role="banner"]',
    '[role="contentinfo"]',
    '[style*="display: none"]',
    '[style*="display:none"]',
]

# 免责声明/版权声明关键词模式
_DISCLAIMER_PATTERNS = [
    r"免责声明[\s\S]*?$",
    r"免责申明[\s\S]*?$",
    r"免责声明[:：]?[\s\S]*?$",
    r"免责申明[:：]?[\s\S]*?$",
    r"风险提示[\s\S]*?$",
    r"版权所有[\s\S]*?$",
    r"投资有风险[\s\S]*?$",
    r"市场有风险[\s\S]*?$",
    r"本报告仅供参考[\s\S]*?$",
    r"扫码关注[\s\S]*?$",
    r"未经许可.*?不得[\s\S]*?$",
    r"Copyright\s.*?$",
    r"All Rights Reserved[\s\S]*?$",
]


class HtmlParser:
    """HTML 文件解析器。

    使用 BeautifulSoup + lxml 解析 HTML，移除噪声节点，
    提取正文文本和表格。

    Usage:
        parser = HtmlParser(config=ParseConfig())
        result = parser.parse("/path/to/report.html")
    """

    def __init__(self, config: ParseConfig | None = None) -> None:
        self.config = config or ParseConfig()
        self._table_count = 0

    def parse(self, file_path: str) -> ParseResult:
        """
        解析 HTML 文件并返回纯文本。

        Args:
            file_path: HTML 文件的本地路径

        Returns:
            ParseResult: 包含解析文本和元数据

        Raises:
            FileNotFoundError_: 文件不存在
            FileReadError: 文件读取或解析失败
            EmptyContentError: 解析结果为空
        """
        self._validate_file(file_path)
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError(
                "beautifulsoup4 未安装，请执行: pip install beautifulsoup4 lxml"
            )

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except UnicodeDecodeError:
            # 尝试 gbk 编码（国内网站常见）
            try:
                with open(file_path, "r", encoding="gbk") as f:
                    html_content = f.read()
            except Exception:
                with open(file_path, "r", encoding="latin-1") as f:
                    html_content = f.read()
        except Exception as exc:
            raise FileReadError(file_path, reason=str(exc)) from exc

        self._table_count = 0

        try:
            soup = BeautifulSoup(html_content, "lxml")
        except Exception:
            # lxml 不可用时降级到 html.parser
            soup = BeautifulSoup(html_content, "html.parser")

        # 1. 移除噪声节点
        self._remove_noise(soup)

        # 2. 选择正文容器，避免整页导航污染正文
        content = self._select_main_content(soup)
        title = self._extract_title(soup, content, file_path)

        # 3. 提取正文容器内的图片资产（表格处理会修改 DOM，所以先收集图片）
        embedded_images = (
            self._extract_embedded_images(content, file_path)
            if self.config.html_extract_embedded_images
            else []
        )

        # 4. 先处理正文表格（转换为 Markdown 后从 DOM 移除，避免重复）
        table_texts = self._process_tables(content)

        # 5. 提取正文文本
        body_text = self._extract_text_from_content(content)

        # 6. 后处理：移除免责声明
        body_text = self._remove_disclaimers(body_text)

        # 7. 对正文图片执行 OCR 和可选 AI 增强
        image_ocr_sections, ai_sections = self._process_embedded_images(
            embedded_images,
            title=title,
            context=body_text,
        )

        raw_text = build_document_text(
            title=title,
            source_file=file_path,
            parser_type=ParserType.HTML.value,
            body_text=body_text,
            table_text=table_texts,
            image_ocr_sections=image_ocr_sections,
            ai_sections=ai_sections,
            max_text_length=self.config.max_text_length,
        )

        if not self._has_meaningful_content(raw_text):
            raise EmptyContentError(
                parser_type=ParserType.HTML.value,
                file_path=file_path,
            )

        # 截断处理
        if len(raw_text) > self.config.max_text_length:
            raw_text = (
                raw_text[: self.config.max_text_length]
                + f"\n\n[文本过长，已截断，原长度: {len(raw_text)} 字符]"
            )

        return ParseResult(
            parser_type=ParserType.HTML,
            raw_text=raw_text,
            metadata={
                "file_path": file_path,
                "tables_found": self._table_count,
                "embedded_images_found": len(embedded_images),
            },
        )

    def parse_html_string(self, html: str) -> str:
        """
        直接解析 HTML 字符串（用于 PDF 内嵌 HTML 或在线内容）。

        Args:
            html: HTML 字符串

        Returns:
            解析后的纯文本
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError("beautifulsoup4 未安装")

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        self._table_count = 0
        self._remove_noise(soup)
        content = self._select_main_content(soup)
        table_texts = self._process_tables(content)
        body_text = self._extract_text_from_content(content)

        parts = [p for p in [body_text.strip(), table_texts] if p.strip()]
        return "\n\n".join(parts)

    # ---- 内部方法 ----

    @staticmethod
    def _validate_file(file_path: str) -> None:
        """验证文件存在且可读。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError_(file_path)
        if not os.path.isfile(file_path):
            raise FileReadError(file_path, reason="路径不是文件")

    def _remove_noise(self, soup: Any) -> None:
        """移除 HTML 中的噪声节点。"""
        # 移除指定标签
        for tag in _REMOVE_TAGS:
            for node in soup.find_all(tag):
                node.decompose()

        # 移除匹配 CSS 选择器的节点
        for selector in _REMOVE_SELECTORS:
            try:
                for node in soup.select(selector):
                    # 避免移除了主要内容容器
                    if not self._is_main_content(node):
                        node.decompose()
            except Exception:
                pass

        # 移除常见交互/悬浮工具条，避免正文抽取被客服、返回顶部污染
        for node in soup.find_all(class_=re.compile(
            r"(yb_|float|fixed|toolbar|service|客服|erwei|qrcode|cb-box|weixin|cont-in-box|f-ser-box)",
            re.I,
        )):
            if not self._is_main_content(node):
                node.decompose()

    @staticmethod
    def _is_main_content(node: Any) -> bool:
        """判断节点是否可能是正文内容（保护不被误删）。"""
        if node is None or getattr(node, "attrs", None) is None:
            return False
        protect_ids = {"content", "main", "article", "post", "entry", "body"}
        protect_classes = {"content", "main", "article", "post", "entry", "body", "text"}

        node_id = (node.get("id") or "").lower()
        node_class = " ".join(node.get("class") or []).lower()

        if any(pid in node_id for pid in protect_ids):
            return True
        if any(pc in node_class for pc in protect_classes):
            return True
        return False

    def _process_tables(self, soup: Any) -> str:
        """提取所有 <table> 并转换为 Markdown，然后从 DOM 移除。"""
        tables = soup.find_all("table")
        if not tables:
            return ""

        results: list[str] = []
        for table in tables:
            md = html_table_to_markdown(
                table,
                add_description=self.config.table_add_description,
            )
            if md.strip():
                results.append(md)
                self._table_count += 1

            # 同时添加纯文本版本辅助理解
            text_desc = extract_table_text(table)
            if text_desc.strip():
                results.append(text_desc)

            # 移除已处理的表格
            table.decompose()

        return "\n\n".join(results)

    def _extract_body(self, soup: Any) -> str:
        """提取 HTML 正文文本。"""
        content = self._select_main_content(soup)
        return self._extract_text_from_content(content)

    def _select_main_content(self, soup: Any) -> Any:
        """通过候选块评分选择最可能的正文容器。"""
        body = soup.body or soup
        candidates: list[Any] = []
        for tag_name in ["article", "main", "section", "div"]:
            candidates.extend(body.find_all(tag_name))

        best = None
        best_score = -1.0
        for node in candidates:
            score = self._score_content_node(node)
            if score > best_score:
                best = node
                best_score = score
        if best is not None and best_score >= 50:
            return best
        return body

    def _score_content_node(self, node: Any) -> float:
        text = node.get_text(separator="\n", strip=True)
        compact = re.sub(r"\s+", "", text)
        if not compact and not node.find_all(["img", "table"]):
            return -1.0

        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", compact))
        paragraph_count = len(node.find_all(["p", "h1", "h2", "h3", "h4"]))
        table_count = len(node.find_all("table"))
        image_count = len(node.find_all("img"))
        links = node.find_all("a")
        link_text_len = sum(len(a.get_text(strip=True)) for a in links)
        link_density = link_text_len / max(len(compact), 1)
        class_id = " ".join(
            [
                str(node.get("id") or ""),
                " ".join(node.get("class") or []),
            ]
        ).lower()
        class_bonus = 0
        if re.search(r"content|conten|article|post|entry|body|text|detail|main|con_p|t-con", class_id):
            class_bonus = 180
        elif re.search(r"\bright\b", class_id) and chinese_chars >= 80:
            class_bonus = 80
        nav_hits = sum(
            text.count(keyword)
            for keyword in [
                "首页", "上一篇", "下一篇", "相关信息", "客服", "下载APP",
                "收藏本页面", "打印", "返回顶部", "导航",
            ]
        )
        hidden_penalty = 10000 if "display: none" in str(node.get("style", "")).lower() else 0

        image_score = image_count * 900
        if image_count and table_count == 0 and chinese_chars < 10:
            image_score = image_count * 20

        return (
            chinese_chars
            + paragraph_count * 35
            + table_count * 120
            + image_score
            + class_bonus
            - link_density * chinese_chars * 1.2
            - nav_hits * 70
            - hidden_penalty
        )

    def _extract_text_from_content(self, content: Any) -> str:
        """从已选正文容器中提取文本。"""
        text = content.get_text(separator="\n", strip=True)

        # 处理保留的 alt 文本
        if self.config.html_keep_alt_text:
            imgs = content.find_all("img")
            for img in imgs:
                alt = img.get("alt", "").strip()
                if alt:
                    text += f"\n[图片说明: {alt}]"

        # 清理多余空白
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)

        return text

    @staticmethod
    def _extract_title(soup: Any, content: Any, file_path: str) -> str:
        for node in [
            content.find(["h1", "h2"]),
            soup.find(["h1", "h2"]),
            soup.find("title"),
        ]:
            if node:
                title = " ".join(node.get_text(" ", strip=True).split())
                if title:
                    return title
        return Path(file_path).stem

    def _extract_embedded_images(self, content: Any, html_file_path: str) -> list[tuple[str, str]]:
        """提取正文内可解析的本地图片，返回 (展示路径, 绝对路径)。"""
        results: list[tuple[str, str]] = []
        base_dir = Path(html_file_path).resolve().parent
        seen: set[str] = set()

        for img in content.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src or src.startswith(("http://", "https://", "data:")):
                continue
            if self._is_noise_image(img, src):
                continue

            image_path = (base_dir / src).resolve()
            if not image_path.exists() or not image_path.is_file():
                continue
            if str(image_path) in seen:
                continue
            if not self._is_meaningful_image(image_path, img):
                continue

            seen.add(str(image_path))
            try:
                display_path = image_path.relative_to(base_dir).as_posix()
            except ValueError:
                display_path = str(image_path)
            results.append((display_path, str(image_path)))

        return results

    @staticmethod
    def _is_noise_image(img: Any, src: str) -> bool:
        descriptor = " ".join(
            [
                src,
                str(img.get("alt") or ""),
                str(img.get("id") or ""),
                " ".join(img.get("class") or []),
            ]
        ).lower()
        return bool(re.search(r"logo|icon|qrcode|qr|erwei|二维码|avatar|button|sprite", descriptor))

    @staticmethod
    def _is_meaningful_image(image_path: Path, img: Any) -> bool:
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                width, height = image.size
        except Exception:
            width = _safe_int(img.get("width"))
            height = _safe_int(img.get("height"))

        if width <= 0 or height <= 0:
            return True
        area = width * height
        return width >= 500 or height >= 500 or area >= 200_000

    def _process_embedded_images(
        self,
        embedded_images: list[tuple[str, str]],
        *,
        title: str,
        context: str,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        image_ocr_sections: list[tuple[str, str]] = []
        ai_sections: list[tuple[str, str]] = []
        image_parser = ImageParser(config=self.config)
        ai_enhancer = ParserAIEnhancer(self.config)

        for index, (display_path, image_path) in enumerate(embedded_images):
            ocr_text = ""
            try:
                ocr_result = image_parser.extract_image_text(image_path)
                ocr_text = ocr_result.raw_text
                if ocr_text.strip():
                    image_ocr_sections.append((display_path, ocr_text))
            except Exception as exc:
                logger.warning("HTML 内嵌图片 OCR 失败 image=%s error=%s", image_path, exc)

            if index < self.config.parser_ai_max_images:
                ai_text = ai_enhancer.enhance_image(
                    image_path=display_path,
                    ocr_text=ocr_text,
                    title=title,
                    context=context,
                )
                if ai_text.strip():
                    ai_sections.append((display_path, ai_text))

        return image_ocr_sections, ai_sections

    def _has_meaningful_content(self, raw_text: str) -> bool:
        content = re.sub(r"^来源文件:.*$|^解析器:.*$", "", raw_text, flags=re.MULTILINE)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", content))
        return len(content.strip()) >= 20 and (
            chinese_chars >= 4
            or len(content.strip()) >= self.config.min_meaningful_text_chars
        )

    @staticmethod
    def _remove_disclaimers(text: str) -> str:
        """移除文本中的免责声明/版权声明行。"""
        for pattern in _DISCLAIMER_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
        return text.strip()


def _safe_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return 0
