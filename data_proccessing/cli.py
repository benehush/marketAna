"""Command line entry point for the standalone data-processing package."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys

from data_proccessing.evaluation.report import write_evaluation_report
from data_proccessing.evaluation.runner import evaluate_dataset
from data_proccessing.instrument_mapping.builder import build_instrument_lexicon, write_build_artifacts
from data_proccessing.instrument_mapping.models import Document as MappingDocument
from data_proccessing.instrument_mapping.runtime import load_runtime_lexicon
from data_proccessing.config import ProcessingConfig
from data_proccessing.llm.client import HttpLLMClient
from data_proccessing.pipeline.batch import run_batch
from data_proccessing.readers.base import read_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="data_proccessing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-lexicon")
    build.add_argument("inputs", nargs="+")
    build.add_argument("--output-dir", default="data_proccessing/instrument_mapping/artifacts")
    process = subparsers.add_parser("process")
    process.add_argument("inputs", nargs="+")
    process.add_argument("--lexicon", default="data_proccessing/instrument_mapping/artifacts/instrument_lexicon.json")
    process.add_argument("--output-dir", default="data_proccessing/output")
    process.add_argument("--skip-llm", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("dataset")
    evaluate.add_argument("--lexicon", default="data_proccessing/instrument_mapping/artifacts/instrument_lexicon.json")
    evaluate.add_argument("--output-dir", default="data_proccessing/evaluation/reports")
    subparsers.add_parser("check-isolation")
    args = parser.parse_args(argv)
    if args.command == "build-lexicon":
        documents = [_mapping_document(path) for path in _expand_texts(args.inputs)]
        result = build_instrument_lexicon(documents)
        write_build_artifacts(result, args.output_dir)
        print(json.dumps(result.report, ensure_ascii=False))
        return 0
    if args.command == "process":
        lexicon = load_runtime_lexicon(args.lexicon)
        config = ProcessingConfig.from_env()
        llm_client = None
        if not args.skip_llm and config.llm_api_key and config.llm_base_url and config.llm_model:
            llm_client = HttpLLMClient(
                api_key=config.llm_api_key,
                base_url=config.llm_base_url,
                model=config.llm_model,
                timeout_seconds=config.llm_timeout_seconds,
                provider=config.llm_provider,
                max_retries=config.llm_max_retries,
            )
        _, report = run_batch(
            args.inputs,
            lexicon,
            output_dir=args.output_dir,
            llm_client=llm_client,
            skip_llm=args.skip_llm,
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if args.command == "evaluate":
        report = evaluate_dataset(args.dataset, load_runtime_lexicon(args.lexicon))
        write_evaluation_report(report, args.output_dir)
        print(json.dumps(report["metrics"], ensure_ascii=False))
        return 0
    if args.command == "check-isolation":
        violations = _isolation_violations()
        if violations:
            for violation in violations:
                print(violation, file=sys.stderr)
            return 1
        print("data_proccessing isolation check passed")
        return 0
    return 1


def _expand_texts(inputs: list[str]) -> list[Path]:
    result: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            result.extend(sorted(path.rglob("*.txt")))
        elif path.is_file():
            result.append(path)
    return result


def _mapping_document(path: Path) -> MappingDocument:
    document = read_path(path)
    return MappingDocument(document.source_id, document.raw_text, document.title, document.file_name)


def _isolation_violations() -> list[str]:
    violations: list[str] = []
    root = Path(__file__).resolve().parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{path}:{exc.lineno}: syntax error: {exc.msg}")
            continue
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [item.name for item in node.names] if isinstance(node, (ast.Import, ast.ImportFrom)) else []
            imported = [module or ""] + names
            if any(item == "back_end" or item.startswith("back_end.") or item == "pn" or item.startswith("pn.") or item.startswith("pn0") or item.startswith("pn1") for item in imported):
                violations.append(f"{path}:{getattr(node, 'lineno', 0)}: forbidden import")
    return violations


if __name__ == "__main__":
    raise SystemExit(main())
