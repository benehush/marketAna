"""
pn04 图片 OCR 解析器

使用 Tesseract OCR 识别图片中的文字。
支持 PNG、JPG、BMP、TIFF、WebP 等常见图片格式。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pn04.document_formatter import build_document_text
from pn04.exceptions import EmptyContentError, FileReadError, FileNotFoundError_, OCRError
from pn04.models import ParseConfig, ParseResult, ParserType

logger = logging.getLogger(__name__)

# 支持的图片扩展名
_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}


class ImageParser:
    """图片 OCR 解析器。

    使用 Pillow 进行图片预处理，pytesseract 进行 OCR 文字识别。
    默认支持中文+英文识别。

    Usage:
        parser = ImageParser(config=ParseConfig())
        result = parser.parse("/path/to/chart.png")
    """

    def __init__(self, config: ParseConfig | None = None) -> None:
        self.config = config or ParseConfig()

    def parse(self, file_path: str) -> ParseResult:
        """
        对图片文件执行 OCR 并返回识别文本。

        Args:
            file_path: 图片文件的本地路径

        Returns:
            ParseResult: 包含 OCR 识别文本和元数据

        Raises:
            FileNotFoundError_: 文件不存在
            FileReadError: 文件读取失败
            OCRError: OCR 识别失败
            EmptyContentError: 识别结果为空
        """
        extracted = self.extract_image_text(file_path)
        formatted = build_document_text(
            title=os.path.basename(file_path),
            source_file=file_path,
            parser_type=ParserType.IMAGE.value,
            body_text=extracted.raw_text,
            max_text_length=self.config.max_text_length,
        )
        return ParseResult(
            parser_type=ParserType.IMAGE,
            raw_text=formatted,
            metadata=extracted.metadata,
        )

    def extract_image_text(self, file_path: str) -> ParseResult:
        """对图片文件执行 OCR，返回未包装的 OCR 文本。"""
        self._validate_file(file_path)
        try:
            from PIL import Image
        except ImportError:
            raise ImportError("Pillow 未安装，请执行: pip install Pillow")

        self._ensure_supported_engine()

        try:
            image = Image.open(file_path)
            metadata: dict[str, Any] = {
                "file_path": file_path,
                "format": image.format,
                "size": image.size,
                "mode": image.mode,
            }

            text = self._ocr_image(image, file_path=file_path)

            text = text.strip()

            if not text:
                raise EmptyContentError(
                    parser_type=ParserType.IMAGE.value,
                    file_path=file_path,
                )

            # 截断处理
            if len(text) > self.config.max_text_length:
                text = (
                    text[: self.config.max_text_length]
                    + f"\n\n[文本过长，已截断，原长度: {len(text)} 字符]"
                )

            return ParseResult(
                parser_type=ParserType.IMAGE,
                raw_text=text,
                metadata=metadata,
            )

        except (EmptyContentError, OCRError, FileNotFoundError_, FileReadError):
            raise
        except Exception as exc:
            raise FileReadError(file_path, reason=str(exc)) from exc

    def ocr_from_bytes(self, image_bytes: bytes) -> str:
        """
        从内存中的图片字节数据执行 OCR（用于 PDF 扫描页降级）。

        Args:
            image_bytes: PNG/JPEG 格式的图片字节数据

        Returns:
            OCR 识别的文本
        """
        try:
            from PIL import Image
            from io import BytesIO

            import pytesseract
        except ImportError:
            logger.warning("OCR 依赖未安装，跳过 OCR")
            return ""

        try:
            image = Image.open(BytesIO(image_bytes))
            text = self._ocr_image(image, file_path="<bytes>")
            return text.strip()
        except Exception as exc:
            logger.warning(f"OCR from bytes 失败: {exc}")
            return ""

    # ---- 内部方法 ----

    @staticmethod
    def _validate_file(file_path: str) -> None:
        """验证文件存在、可读、格式支持。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError_(file_path)
        if not os.path.isfile(file_path):
            raise FileReadError(file_path, reason="路径不是文件")

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise FileReadError(
                file_path,
                reason=f"不支持的图片格式: {ext}，支持: {_SUPPORTED_EXTENSIONS}",
            )

    def _ensure_supported_engine(self) -> None:
        engine = (self.config.image_ocr_engine or "tesseract").lower()
        if engine == "tesseract":
            try:
                import pytesseract  # noqa: F401
            except ImportError:
                raise ImportError(
                    "pytesseract 未安装，请执行: pip install pytesseract\n"
                    "同时需要安装 Tesseract OCR 引擎: "
                    "https://github.com/tesseract-ocr/tesseract"
                )
            return
        if engine == "paddle":
            raise OCRError("PaddleOCR 引擎尚未启用，请使用 image_ocr_engine='tesseract'")
        raise OCRError(f"不支持的 OCR 引擎: {self.config.image_ocr_engine}")

    def _ocr_image(self, image: Any, *, file_path: str) -> str:
        """对普通图片或长图执行 OCR。"""
        self._ensure_supported_engine()
        width, height = image.size
        slice_height = max(600, int(self.config.image_slice_height))
        if height <= slice_height * 1.5:
            return self._ocr_pil_image(image, file_path=file_path)

        parts: list[str] = []
        total = (height + slice_height - 1) // slice_height
        for index, top in enumerate(range(0, height, slice_height), start=1):
            bottom = min(top + slice_height, height)
            crop = image.crop((0, top, width, bottom))
            text = self._ocr_pil_image(crop, file_path=file_path)
            if text.strip():
                parts.append(f"[图片分片 {index}/{total}]\n{text.strip()}")
        return "\n\n".join(parts)

    def _ocr_pil_image(self, image: Any, *, file_path: str) -> str:
        import pytesseract

        processed = self._preprocess(image)
        try:
            return pytesseract.image_to_string(
                processed,
                lang=self.config.ocr_lang,
            )
        except pytesseract.TesseractError as exc:
            raise OCRError(
                f"Tesseract OCR 执行失败: {exc}",
                detail={"file_path": file_path},
            ) from exc
        except Exception as exc:
            raise OCRError(
                f"OCR 失败: {exc}",
                detail={"file_path": file_path},
            ) from exc

    def _preprocess(self, image: Any) -> Any:
        """
        图片预处理：增强 OCR 识别准确率。

        步骤: 转灰度 → 对比度增强 → 锐化 → 放大（小字体场景）
        """
        from PIL import Image, ImageEnhance, ImageFilter

        # 1. 透明图层合成到白底，避免 OCR 背景变黑
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            background.alpha_composite(rgba)
            image = background.convert("RGB")
        if image.mode != "L":
            image = image.convert("L")

        # 2. 对比度增强
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.5)

        # 3. 锐化
        image = image.filter(ImageFilter.SHARPEN)

        # 3.5 可选二值化
        if self.config.image_binarize:
            image = image.point(lambda x: 255 if x > 180 else 0)

        # 4. 放大（小图片）
        width, height = image.size
        if width < 800 or height < 800:
            scale = max(2, min(4, 1600 // min(width, height)))
            image = image.resize(
                (width * scale, height * scale),
                Image.LANCZOS,
            )

        return image
