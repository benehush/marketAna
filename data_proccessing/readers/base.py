"""Reader protocol and file-type dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from data_proccessing.models import Document


class Reader(Protocol):
    def __call__(self, path: str | Path) -> Document: ...


def read_path(path: str | Path, *, ocr: object | None = None) -> Document:
    file_path = Path(path)
    suffix = file_path.suffix.casefold()
    if suffix in {".txt", ".md", ".log", ".json", ".jsonl"}:
        from data_proccessing.readers.text_reader import read_text

        return read_text(file_path)
    if suffix in {".html", ".htm"}:
        from data_proccessing.readers.html_reader import read_html

        return read_html(file_path)
    if suffix == ".pdf":
        from data_proccessing.readers.pdf_reader import read_pdf

        return read_pdf(file_path)
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        from data_proccessing.readers.image_reader import read_image

        return read_image(file_path, ocr=ocr)
    raise ValueError(f"unsupported document type: {file_path.suffix or '<none>'}")
