"""Batch runner with per-document failure isolation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from data_proccessing.instrument_mapping.runtime import RuntimeLexicon
from data_proccessing.llm.client import LLMClient
from data_proccessing.pipeline.outputs import write_results
from data_proccessing.pipeline.processor import DocumentProcessingResult, process_document
from data_proccessing.readers.base import read_path


def expand_paths(paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.casefold() in {".txt", ".md", ".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}))
        elif path.is_file():
            files.append(path)
    return files


def run_batch(
    paths: Iterable[str | Path],
    lexicon: RuntimeLexicon,
    *,
    output_dir: str | Path,
    llm_client: LLMClient | None = None,
    skip_llm: bool = False,
) -> tuple[list[DocumentProcessingResult], dict[str, int]]:
    results: list[DocumentProcessingResult] = []
    for path in expand_paths(paths):
        try:
            document = read_path(path)
            results.append(process_document(document, lexicon, llm_client=llm_client, skip_llm=skip_llm))
        except Exception as exc:
            from data_proccessing.models import Document, ProcessingError

            document = Document(source_id=str(path), raw_text="", file_name=path.name, file_type=path.suffix.lstrip("."))
            results.append(
                DocumentProcessingResult(
                    document=document,
                    matches=(),
                    signals=(),
                    analyses=(),
                    errors=(f"reader_error: {exc}",),
                    processing_stats={"duration_ms": 0},
                )
            )
    report = write_results(results, output_dir)
    return results, report
