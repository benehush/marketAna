"""
Batch pipeline runner — like manual_single_file_pipeline.py but for all files in a directory.

Usage:
    uv run python tests/manual_batch_pipeline.py data/test_sample --output-dir tests/outputs
    uv run python tests/manual_batch_pipeline.py data/test_sample --output-dir tests/outputs --skip-llm
    uv run python tests/manual_batch_pipeline.py data/20250401 --output-dir tests/outputs --limit 20
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.repositories.articles import ArticleRepository
from pn04.parser import parse_article
from pn05.cleaner import clean_article
from pn06.rule_engine import analyze_article
from pn07.llm_infer import infer_article
from pn07.models import LLMConfig

SUPPORTED_TYPES = {
    ".pdf": "pdf", ".html": "html", ".htm": "html",
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".bmp": "image", ".tiff": "image", ".tif": "image",
    ".webp": "image", ".gif": "image",
}


def main():
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"目录不存在: {root}")

    files = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_TYPES
        and "img_folder" not in str(p).lower()
    )
    if args.limit:
        files = files[: args.limit]

    print(f"Found {len(files)} files to process\n")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []

    for i, file_path in enumerate(files, 1):
        rel = file_path.relative_to(root)
        file_type = SUPPORTED_TYPES[file_path.suffix.lower()]
        print(f"[{i:3d}/{len(files)}] {rel!s:70s} ", end="", flush=True)

        t0 = time.monotonic()
        session_factory = build_session_factory()
        session = session_factory()
        try:
            repo = ArticleRepository(session)
            article = repo.create_article(
                title=file_path.stem,
                source="batch_pipeline",
                company=file_path.stem.split("_", 1)[0] if "_" in file_path.stem else None,
                file_url=file_path.as_posix(),
                file_type=file_type,
            )
            session.commit()

            raw_text = parse_article(article, session)
            session.commit()

            cleaned_text = clean_article(article.id, session)
            session.commit()

            rule_result = analyze_article(article.id, session)
            session.commit()

            llm_info = "skipped"
            if not args.skip_llm:
                config = LLMConfig.from_settings()
                if config.is_configured:
                    llm_result = infer_article(article.id, session, config=config)
                    session.commit()
                    llm_info = _fmt_llm_summary(llm_result)
                else:
                    llm_info = "LLM not configured"

            elapsed = int((time.monotonic() - t0) * 1000)

            # Write outputs per file
            file_out = output_dir / file_path.stem
            file_out.mkdir(parents=True, exist_ok=True)
            (file_out / "01_raw.txt").write_text(raw_text or "", encoding="utf-8")
            (file_out / "02_cleaned.txt").write_text(cleaned_text or "", encoding="utf-8")
            _write_recognition(file_out / "03_recognition.txt", rule_result, llm_info)

            raw_len = len(raw_text or "")
            cleaned_len = len(cleaned_text or "")
            removal = f"{(1 - cleaned_len / max(raw_len, 1)) * 100:.1f}%"
            direction = rule_result.direction or "-"
            product = rule_result.product or "-"

            summary_rows.append({
                "file": str(rel),
                "type": file_type,
                "raw_chars": raw_len,
                "cleaned_chars": cleaned_len,
                "removal_pct": removal,
                "product": product,
                "direction": direction,
                "confidence": f"{rule_result.confidence:.2f}",
                "llm": llm_info[:40],
                "duration_ms": elapsed,
            })
            print(f"OK  raw={raw_len:5d}  cleaned={cleaned_len:5d}  {removal:>6s}  "
                  f"→{product}:{direction}  ({elapsed}ms)")

        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            summary_rows.append({
                "file": str(rel), "type": file_type,
                "raw_chars": 0, "cleaned_chars": 0, "removal_pct": "FAIL",
                "product": "-", "direction": "-", "confidence": "-",
                "llm": str(exc)[:40], "duration_ms": elapsed,
            })
            print(f"FAIL  {exc}")

        finally:
            session.close()
            Base.metadata.drop_all(bind=session_factory.kw["bind"])
            session_factory.kw["bind"].dispose()

    # Summary CSV
    import csv
    summary_path = output_dir / "_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()) if summary_rows else [])
        w.writeheader()
        w.writerows(summary_rows)

    ok = [r for r in summary_rows if r["removal_pct"] != "FAIL"]
    print(f"\n{'='*70}")
    print(f"  Done: {len(ok)}/{len(summary_rows)} OK  |  Output: {output_dir}")
    print(f"  Summary: {summary_path}")
    if ok:
        removals = [float(r["removal_pct"].rstrip("%")) for r in ok]
        print(f"  Avg removal: {sum(removals)/len(removals):.1f}%")


def build_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _write_recognition(path: Path, rule_result, llm_info: str):
    lines = ["# 规则识别结果"]
    if rule_result.results:
        for idx, item in enumerate(rule_result.results, 1):
            lines.extend([
                f"{idx}. 品种: {item.product or '未知'}",
                f"   方向: {item.direction or '未知'}",
                f"   置信度: {item.confidence:.2f}",
                f"   需LLM: {item.need_llm}",
                f"   理由: {item.reason or ''}",
            ])
    else:
        lines.append("未识别到。")
    lines.extend(["", "# LLM 识别结果", llm_info])
    path.write_text("\n".join(lines), encoding="utf-8")


def _fmt_llm_summary(llm_result) -> str:
    if not llm_result.results:
        return f"无结果 (error={llm_result.error_msg[:30] if llm_result.error_msg else ''})"
    items = [f"{r.product}:{r.direction}:{r.confidence:.2f}" for r in llm_result.results]
    return "; ".join(items)


def parse_args():
    p = argparse.ArgumentParser(description="Batch pipeline runner for MarketANA")
    p.add_argument("root", type=Path, help="Root directory with test files")
    p.add_argument("--output-dir", type=Path, default=Path("tests/outputs"), help="Output directory")
    p.add_argument("--limit", type=int, default=None, help="Max files to process")
    p.add_argument("--skip-llm", action="store_true", help="Skip LLM stages")
    return p.parse_args()


if __name__ == "__main__":
    main()
