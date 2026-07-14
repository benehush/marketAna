"""Image reader with an injectable OCR function."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Any

from data_proccessing.models import Document


def read_image(path: str | Path, *, ocr: Callable[[Any], str] | None = None) -> Document:
    file_path = Path(path)
    if ocr is None:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("image OCR requires pytesseract and Pillow, or an injected ocr callable") from exc
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        engine = "pytesseract"
    else:
        from PIL import Image

        text = ocr(Image.open(file_path))
        engine = "injected"
    return Document(
        source_id=str(file_path),
        raw_text=text or "",
        title=file_path.stem,
        file_name=file_path.name,
        file_type="image",
        metadata={"ocr_engine": engine},
    )
