from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from back_end.app.core.database import get_session
from back_end.app.core.display import formal_analysis_clause
from back_end.app.core.responses import success_response
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article 
from pn05.display_cleaner import clean_display_text
from data_proccessing.catalog import product_group

router = APIRouter(prefix="/api/products", tags=["products"])

@router.get("")
def get_products(session: Session = Depends(get_session)) -> dict:
    stmt = (
        select(AnalysisResult, Article)
        .join(Article, Article.id == AnalysisResult.article_id)
        .where(
            Article.status == ArticleProcessingStatus.STORED.value,
            formal_analysis_clause(AnalysisResult),
        )
        .order_by(AnalysisResult.product.asc(), Article.publish_time.desc())
    )

    grouped: dict[tuple[str, str], list[dict]] = {}
    best_by_article_product: dict[tuple[int, str], tuple[AnalysisResult, Article]] = {}

    for result, article in session.execute(stmt).all():
        product = result.product or ""
        key = (article.id, result.product_key or product)
        current = best_by_article_product.get(key)
        if current is None or _product_prediction_rank(result) > _product_prediction_rank(current[0]):
            best_by_article_product[key] = (result, article)

    for result, article in best_by_article_product.values():
        product = result.product
        date_source = article.publish_time or result.analysis_time

        group_key = (result.product_key or "", product)
        if group_key not in grouped:
            grouped[group_key] = []
        grouped[group_key].append(
            {
                "article_id": article.id,
                "result_id": result.id,
                "direction": result.direction,
                "confidence": result.confidence,
                "company": article.company or article.source or "",
                "date": date_source.date().isoformat() if date_source else "",
                "reason": clean_display_text(result.reason),
                "contract": result.contract,
                "need_manual_review": result.need_manual_review,
            }
        )

    data = []
    for (product_key, product), predictions in grouped.items():
        data.append({
            "product": product,
            "product_key": product_key,
            "product_group": product_group(product_key),
            "predictions": predictions,
        })

    return success_response(data)


def _product_prediction_rank(result: AnalysisResult) -> tuple[int, float, int]:
    """Rank duplicate article/product predictions for product overview cards."""
    return (
        1 if result.is_primary else 0,
        float(result.confidence or 0.0),
        int(result.id or 0),
    )
