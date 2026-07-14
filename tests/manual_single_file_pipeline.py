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
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from back_end.app.core.database import Base, create_database_tables
from back_end.app.models.article import TaskLog
from back_end.app.repositories.articles import ArticleRepository
from pn04.parser import parse_article
from pn05.cleaner import clean_article
from pn05.product_segmenter import segment_article
from pn05.refiner import refine_article
from pn06.rule_engine import analyze_article
from pn06.product_resolver import resolve_article_products
from pn07.llm_infer import infer_article
from pn07.models import LLMConfig


CLEAN_PROGRESS_STEPS = 7

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

        with StageStatus("解析文档"):
            raw_text = parse_article(article, session)
        session.commit()
        write_output_file(args.output_dir, "01_parsed_raw_text.txt", raw_text)

        with ConsoleProgressBar(total=CLEAN_PROGRESS_STEPS, label="清洗进度") as clean_progress:
            cleaned_text = clean_article(
                article.id,
                session,
                progress_callback=clean_progress.step,
            )
            clean_progress.complete("清洗完成")
        session.commit()
        write_output_file(args.output_dir, "02_cleaned_text.txt", cleaned_text)

        with StageStatus("品种分段"):
            segment_article(article.id, session)
        session.commit()
        if not args.skip_llm:
            config = LLMConfig.from_settings()
            if config.is_configured:
                with StageStatus("未知品种归一化"):
                    resolve_article_products(article.id, session, config=config)
                session.commit()
        refined_text = ""
        if not args.skip_llm:
            config = LLMConfig.from_settings()
            if config.is_configured:
                with StageStatus("LLM 分段精修", detail="正在等待文华接口返回，耗时较长是正常的"):
                    refined_text = refine_article(article.id, session, config=config) or latest_stage_message(
                        repo,
                        article.id,
                        "refiner",
                        default="LLM 分段精修失败：未返回精修文本，且未找到失败日志。",
                    )
                session.commit()
            else:
                refined_text = "LLM 分段精修已跳过：LLM API 未配置。"
        else:
            refined_text = "LLM 分段精修已跳过。"
        write_output_file(args.output_dir, "04_refined_text.txt", refined_text)
        product_segments_text = format_product_segments(repo.get_product_segments(article.id))
        write_output_file(args.output_dir, "05_product_segments.txt", product_segments_text)

        with StageStatus("规则识别"):
            rule_result = analyze_article(article.id, session, reason_llm_enabled=not args.skip_llm)
        session.commit()

        llm_text = "LLM 识别已跳过。"
        if not args.skip_llm:
            config = LLMConfig.from_settings()
            if config.is_configured:
                with StageStatus("LLM 识别", detail="正在等待文华接口返回，耗时较长是正常的"):
                    llm_result = infer_article(article.id, session, config=config)
                session.commit()
                llm_text = format_llm_result(llm_result)
            else:
                llm_text = "LLM 识别已跳过：LLM API 未配置。"

        recognition_text = format_recognition_text(rule_result, llm_text)
        write_output_file(args.output_dir, "03_recognition_text.txt", recognition_text)
        outputs = {
            "01_parsed_raw_text.txt": raw_text,
            "02_cleaned_text.txt": cleaned_text,
            "03_recognition_text.txt": recognition_text,
            "04_refined_text.txt": refined_text,
            "05_product_segments.txt": product_segments_text,
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
    parser.add_argument("--output-dir", type=Path, help="将五段输出写入该目录")
    return parser.parse_args()


class ConsoleProgressBar:
    """Small stderr progress bar for the manual single-file runner."""

    def __init__(self, *, total: int, label: str, width: int = 28) -> None:
        self.total = max(1, total)
        self.label = label
        self.width = max(10, width)
        self.current = 0
        self._finished = False

    def __enter__(self) -> "ConsoleProgressBar":
        self._render("准备开始")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._finished:
            self._render("清洗失败" if exc_type else "清洗结束")
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._finished = True
        return False

    def step(self, message: str) -> None:
        if self._finished:
            return
        self.current = min(self.current + 1, self.total)
        self._render(message)

    def complete(self, message: str = "完成") -> None:
        if self._finished:
            return
        self.current = self.total
        self._render(message)
        sys.stderr.write("\n")
        sys.stderr.flush()
        self._finished = True

    def _render(self, message: str) -> None:
        ratio = self.current / self.total
        filled = min(self.width, int(self.width * ratio))
        bar = "#" * filled + "-" * (self.width - filled)
        percent = int(ratio * 100)
        sys.stderr.write(f"\r{self.label} [{bar}] {self.current}/{self.total} {percent:3d}% {message}")
        sys.stderr.flush()


class StageStatus:
    """Print start/end status for stages that do not have granular progress."""

    def __init__(self, label: str, *, detail: str = "") -> None:
        self.label = label
        self.detail = detail
        self.start_time = 0.0

    def __enter__(self) -> "StageStatus":
        self.start_time = time.monotonic()
        suffix = f" - {self.detail}" if self.detail else ""
        sys.stderr.write(f"{self.label}开始{suffix}\n")
        sys.stderr.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration_ms = int((time.monotonic() - self.start_time) * 1000)
        status = "失败" if exc_type else "完成"
        sys.stderr.write(f"{self.label}{status} [{duration_ms}ms]\n")
        sys.stderr.flush()
        return False


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


def format_product_segments(segments) -> str:
    lines = ["# 品种分段结果"]
    if not segments:
        lines.append("未生成品种分段。")
        return "\n".join(lines)
    for index, segment in enumerate(segments, start=1):
        lines.extend(
            [
                f"## {index}. {segment.product}",
                f"section_type: {segment.section_type}",
                f"contract: {segment.contract or ''}",
                f"confidence: {segment.confidence:.2f}",
                f"range: {segment.start_char}-{segment.end_char}",
                f"heading: {segment.heading or ''}",
                "",
                "### cleaned_text",
                segment.cleaned_text or "",
            ]
        )
        if segment.refined_text:
            lines.extend(["", "### refined_text", segment.refined_text])
        lines.append("")
    return "\n".join(lines).strip()


def latest_stage_message(repo: ArticleRepository, article_id: int, stage: str, *, default: str) -> str:
    repo.session.flush()
    log = repo.session.scalar(
        select(TaskLog)
        .where(TaskLog.article_id == article_id, TaskLog.stage == stage)
        .order_by(TaskLog.id.desc())
        .limit(1)
    )
    if log is None:
        return default
    status = log.status or "unknown"
    message = log.message or default
    return f"{stage} {status}: {message}"


def print_outputs(outputs: dict[str, str]) -> None:
    for filename, content in outputs.items():
        print(f"\n\n===== {filename} =====\n")
        print(content or "")


def write_outputs(output_dir: Path, outputs: dict[str, str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in outputs.items():
        (output_dir / filename).write_text(content or "", encoding="utf-8")
    print(f"\n输出文件已写入: {output_dir.resolve()}")


def write_output_file(output_dir: Path | None, filename: str, content: str) -> None:
    if output_dir is None:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / filename).write_text(content or "", encoding="utf-8")
    sys.stderr.write(f"已写入: {(output_dir / filename).resolve()}\n")
    sys.stderr.flush()


if __name__ == "__main__":
    main()
