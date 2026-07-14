from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from back_end.app.core.database import get_session
from back_end.app.core.display import formal_analysis_clause
from back_end.app.core.responses import success_response
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article
from data_proccessing.catalog import product_group

router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("")
def get_trends(
    product: str | None = None,
    product_key: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    session: Session = Depends(get_session),
) -> dict:
    stmt = (
        select(AnalysisResult, Article)
        .join(Article, Article.id == AnalysisResult.article_id)
        .where(
            Article.status == ArticleProcessingStatus.STORED.value,
            formal_analysis_clause(AnalysisResult),
        )
        .order_by(Article.publish_time.asc(), AnalysisResult.product.asc())
    )
    if product:
        stmt = stmt.where(AnalysisResult.product == product)
    if product_key:
        stmt = stmt.where(AnalysisResult.product_key == product_key)
    if start_time is not None:
        stmt = stmt.where((Article.publish_time >= start_time) | (AnalysisResult.analysis_time >= start_time))
    if end_time is not None:
        stmt = stmt.where((Article.publish_time <= end_time) | (AnalysisResult.analysis_time <= end_time))

    grouped: dict[tuple[str, str, str], list[float]] = {}
    for result, article in session.execute(stmt).all():
        date_source = article.publish_time or result.analysis_time
        if date_source is None:
            continue

        value = direction_to_heatmap_value(result.direction, result.confidence)
        key = (date_source.date().isoformat(), result.product_key or "", result.product)
        grouped.setdefault(key, []).append(value)

    data = [
        {
            "date": date,
            "product": product_name,
            "product_key": key,
            "product_group": product_group(key),
            "value": round(sum(values) / len(values), 4),
        }
        for (date, key, product_name), values in grouped.items()
    ]
    data.sort(key=lambda item: (item["date"], item["product"]))
    return success_response(data)


def direction_to_heatmap_value(direction: str, confidence: float) -> float:
    if direction == "看涨":
        return confidence
    if direction == "看跌":
        return -confidence
    return 0.0
