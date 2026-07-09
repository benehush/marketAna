"""
Manual single-file pipeline runner.

Run the real parser, cleaner, rule engine, LLM inference, and LLM refiner against
one local file path without writing to the project database.

Examples:
    uv run python tests/manual_single_file_pipeline.py data/20250401/323354/report.html
    uv run python tests/manual_single_file_pipeline.py /abs/path/report.pdf --output-dir /tmp/marketana_debug
    uv run python tests/manual_single_file_pipeline.py data/sample.html --skip-llm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from back_end.app.core.database import Base, create_database_tables
from back_end.app.repositories.articles import ArticleRepository
from pn04.parser import parse_article
from pn05.cleaner import clean_article
from pn05.refiner import refine_article
from pn06.rule_engine import analyze_article
from pn07.llm_infer import infer_article
from pn07.models import LLMConfig


SUPPORTED_TYPES = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".tif": "image",
    ".webp": "image",
    ".gif": "image",
}


def main() -> None:
    args = parse_args()
    file_path = args.file.resolve()
    if not file_path.exists() or not file_path.is_file():
        raise SystemExit(f"文件不存在: {file_path}")

    file_type = args.file_type or detect_file_type(file_path)
    if file_type is None:
        raise SystemExit(f"不支持的文件类型: {file_path.suffix or '<none>'}")

    session_factory = build_session_factory()
    session = session_factory()
    try:
        repo = ArticleRepository(session)
        article = repo.create_article(
            title=args.title or file_path.stem,
            source="manual_single_file_pipeline",
            company=args.company,
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

        llm_text = "LLM 识别已跳过。"
        if not args.skip_llm:
            config = LLMConfig.from_settings()
            if config.is_configured:
                llm_result = infer_article(article.id, session, config=config)
                session.commit()
                llm_text = format_llm_result(llm_result)
            else:
                llm_text = "LLM 识别已跳过：LLM API 未配置。"

        refined_text = ""
        if not args.skip_llm:
            config = LLMConfig.from_settings()
            if config.is_configured:
                refined_text = refine_article(article.id, session, config=config) or ""
                session.commit()
            else:
                refined_text = "LLM 精修已跳过：LLM API 未配置。"
        else:
            refined_text = "LLM 精修已跳过。"

        recognition_text = format_recognition_text(rule_result, llm_text)
        outputs = {
            "01_parsed_raw_text.txt": raw_text,
            "02_cleaned_text.txt": cleaned_text,
            "03_recognition_text.txt": recognition_text,
            "04_refined_text.txt": refined_text,
        }

        print_outputs(outputs)
        if args.output_dir:
            write_outputs(args.output_dir, outputs)

    finally:
        session.close()
        Base.metadata.drop_all(bind=session_factory.kw["bind"])
        session_factory.kw["bind"].dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MarketANA stages for one local file.")
    parser.add_argument("file", type=Path, help="要测试的 PDF/HTML/图片文件路径")
    parser.add_argument("--file-type", choices=["pdf", "html", "image"], help="手动指定文件类型")
    parser.add_argument("--title", help="临时文章标题，默认使用文件名")
    parser.add_argument("--company", help="临时期货公司名称")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 识别和 LLM 精修")
    parser.add_argument("--output-dir", type=Path, help="将四段输出写入该目录")
    return parser.parse_args()


def build_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def detect_file_type(path: Path) -> str | None:
    return SUPPORTED_TYPES.get(path.suffix.lower())


def format_recognition_text(rule_result, llm_text: str) -> str:
    lines = ["# 规则识别结果"]
    if rule_result.results:
        for index, item in enumerate(rule_result.results, start=1):
            lines.extend(
                [
                    f"{index}. 品种: {item.product or '未知'}",
                    f"   方向: {item.direction or '未知'}",
                    f"   置信度: {item.confidence:.2f}",
                    f"   是否需要 LLM: {item.need_llm}",
                    f"   理由: {item.reason or ''}",
                ]
            )
    else:
        lines.append("未识别到规则结果。")

    lines.extend(["", "# LLM 识别结果", llm_text])
    return "\n".join(lines).strip()


def format_llm_result(llm_result) -> str:
    lines: list[str] = []
    if llm_result.results:
        for index, item in enumerate(llm_result.results, start=1):
            lines.extend(
                [
                    f"{index}. 品种: {item.product or '未知'}",
                    f"   合约: {item.contract or ''}",
                    f"   方向: {item.direction or '未知'}",
                    f"   置信度: {item.confidence:.2f}",
                    f"   待人工确认: {item.need_manual_review}",
                    f"   理由: {item.reason or ''}",
                ]
            )
    else:
        lines.append("LLM 未返回可用结果。")
    if llm_result.error_msg:
        lines.extend(["", f"错误信息: {llm_result.error_msg}"])
    if llm_result.raw_response:
        lines.extend(["", "# LLM 原始响应", llm_result.raw_response])
    return "\n".join(lines).strip()


def print_outputs(outputs: dict[str, str]) -> None:
    for filename, content in outputs.items():
        print(f"\n\n===== {filename} =====\n")
        print(content or "")


def write_outputs(output_dir: Path, outputs: dict[str, str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in outputs.items():
        (output_dir / filename).write_text(content or "", encoding="utf-8")
    print(f"\n输出文件已写入: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
