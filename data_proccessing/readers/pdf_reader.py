"""PDF text reader independent of the legacy parser."""

from __future__ import annotations

from pathlib import Path

import fitz

from data_proccessing.models import Document


def read_pdf(path: str | Path) -> Document:
    file_path = Path(path)
    pages: list[str] = []
    with fitz.open(file_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            page_text = page.get_text("text") or ""
            pages.append(f"[PAGE {page_number}]\n{page_text}")
    return Document(
        source_id=str(file_path),
        raw_text="\n".join(pages).strip(),
        title=file_path.stem,
        file_name=file_path.name,
        file_type="pdf",
        metadata={"page_count": len(pages), "parser": "pymupdf"},
    )
