"""Read-only CLI for building sample instrument mapping artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_proccessing.instrument_mapping.builder import build_instrument_lexicon, write_build_artifacts
from data_proccessing.instrument_mapping.models import BuildConfig, Document
from data_proccessing.instrument_mapping.progress import ProgressCallback, TerminalProgressBar


def main() -> None:
    parser = argparse.ArgumentParser(description="Build guided instrument keyword mapping artifacts.")
    parser.add_argument("inputs", nargs="+", help="Raw text files to scan.")
    parser.add_argument("--output-dir", default="data_proccessing/instrument_mapping/artifacts")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of files to read.")
    parser.add_argument("--no-progress", action="store_true", help="Disable terminal progress bars.")
    args = parser.parse_args()

    progress = TerminalProgressBar(enabled=not args.no_progress)
    documents = _load_documents(args.inputs, limit=args.limit, progress_callback=progress)
    result = build_instrument_lexicon(documents, config=BuildConfig(), progress_callback=progress)
    write_build_artifacts(result, args.output_dir, progress_callback=progress)
    print(
        {
            "documents": result.report["documents"],
            "candidate_count": result.report["candidate_count"],
            "status_counts": result.report["status_counts"],
            "output_dir": str(Path(args.output_dir)),
        }
    )


def _load_documents(
    paths: list[str],
    *,
    limit: int = 0,
    progress_callback: ProgressCallback | None = None,
) -> list[Document]:
    documents: list[Document] = []
    input_files = _expand_input_files(paths, limit=limit)
    total = len(input_files)
    for index, path in enumerate(input_files, start=1):
        documents.append(_document_from_path(path))
        if progress_callback:
            progress_callback("read files", index, total, str(path))
    return documents


def _expand_input_files(paths: list[str], *, limit: int = 0) -> list[Path]:
    input_files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            for child in sorted(path.rglob("*.txt")):
                input_files.append(child)
                if limit and len(input_files) >= limit:
                    return input_files
        else:
            input_files.append(path)
            if limit and len(input_files) >= limit:
                return input_files
    return input_files


def _document_from_path(path: Path) -> Document:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.strip("# ").strip()
            break
    return Document(source_id=str(path), raw_text=text, title=title, file_name=path.name)


if __name__ == "__main__":
    main()
