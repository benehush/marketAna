"""Standalone document and batch processing."""

from data_proccessing.pipeline.processor import DocumentProcessingResult, process_document
from data_proccessing.pipeline.canonical import (
    CANONICAL_VERSION,
    to_canonical_result,
    validate_canonical_result,
)

__all__ = [
    "CANONICAL_VERSION",
    "DocumentProcessingResult",
    "process_document",
    "to_canonical_result",
    "validate_canonical_result",
]
