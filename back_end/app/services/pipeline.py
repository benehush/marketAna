"""Backend entrypoint for the standalone data-processing pipeline."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from data_proccessing.config import ProcessingConfig
from data_proccessing.instrument_mapping.runtime import load_runtime_lexicon
from data_proccessing.llm.client import HttpLLMClient
from data_proccessing.models import Document
from data_proccessing.pipeline import process_document, to_canonical_result
from data_proccessing.readers.base import read_path

from back_end.app.api.schemas import datetime_to_iso
from back_end.app.core.config import get_settings
from sqlalchemy import select

from back_end.app.models import Article, ProductAlias
from back_end.app.repositories.articles import ArticleRepository
from back_end.app.services.ingestion import ingest_canonical_result


LEXICON_PATH = Path(__file__).resolve().parents[3] / "data_proccessing/instrument_mapping/artifacts/instrument_lexicon.json"


def run_pipeline(article_id: int, session: Any) -> bool:
    """Process one article and import its canonical result in one transaction."""
    repo = ArticleRepository(session)
    article = repo.get_article_detail(article_id)
    if article is None:
        return False
    started = time.monotonic()
    try:
        document = _document_for_article(article)
        config = ProcessingConfig.from_env()
        lexicon = load_runtime_lexicon(
            LEXICON_PATH,
            dynamic_aliases=_approved_aliases(session),
        )
        settings = get_settings()
        llm_client = _llm_client(settings, config)
        processed = process_document(
            document,
            lexicon,
            llm_client=llm_client,
            config=config,
            skip_llm=llm_client is None,
        )
        canonical = to_canonical_result(processed, pipeline_version=config.pipeline_version)
        ingest_canonical_result(session, canonical, article_id=article_id)
        repo.save_task_log(
            article_id=article_id,
            stage="pipeline",
            status="success" if not processed.errors else "partial",
            message=(
                f"standalone pipeline completed; reviews={len(canonical['review_queue'])}; "
                f"llm_failures={len(processed.errors)}; "
                f"llm_retries={processed.processing_stats.get('llm_retry_count', 0)}; "
                f"llm_recovered={processed.processing_stats.get('llm_recovered_count', 0)}"
            ),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return True
    except Exception as exc:
        session.rollback()
        # Start a fresh ORM lookup after rollback so failure state is persisted.
        repo = ArticleRepository(session)
        article = repo.get_article(article_id)
        if article is not None:
            repo.mark_failed(
                article_id,
                stage="pipeline",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return False


def _document_for_article(article: Article) -> Document:
    path = Path(article.file_url) if article.file_url else None
    if path is not None and path.exists() and path.is_file():
        loaded = read_path(path)
        return Document(
            source_id=article.file_url or loaded.source_id,
            raw_text=loaded.raw_text,
            title=article.title or loaded.title,
            file_name=loaded.file_name,
            file_type=article.file_type or loaded.file_type,
            metadata={**loaded.metadata, "source": article.source or "", "company": article.company or "", "publish_time": datetime_to_iso(article.publish_time)},
            source=article.source or "",
            company=article.company or "",
            publish_time=datetime_to_iso(article.publish_time),
        )
    raw_text = article.text.raw_text if article.text else ""
    cleaned_text = article.text.cleaned_text if article.text else ""
    return Document(
        source_id=article.file_url or f"article:{article.id}",
        raw_text=raw_text,
        title=article.title,
        file_name=Path(article.file_url).name if article.file_url else "",
        file_type=article.file_type or "txt",
        metadata={"source": article.source or "", "company": article.company or "", "publish_time": datetime_to_iso(article.publish_time)},
        cleaned_text=cleaned_text,
        source=article.source or "",
        company=article.company or "",
        publish_time=datetime_to_iso(article.publish_time),
    )


def _llm_client(settings: Any, config: ProcessingConfig) -> HttpLLMClient | None:
    api_key = config.llm_api_key or settings.llm_api_key or ""
    base_url = config.llm_base_url or settings.llm_base_url or ""
    model = config.llm_model or settings.llm_model or ""
    if not api_key or not base_url or not model:
        return None
    return HttpLLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=settings.llm_timeout_seconds or config.llm_timeout_seconds,
        provider=settings.llm_provider or config.llm_provider,
        max_retries=settings.llm_max_retries,
    )


def _approved_aliases(session: Any) -> dict[str, str]:
    rows = session.scalars(select(ProductAlias).where(ProductAlias.status == "approved")).all()
    return {row.alias: row.product_key for row in rows if row.alias and row.product_key}
