from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from back_end.app.core.database import get_session
from back_end.app.core.display import displayable_product_clause
from back_end.app.core.responses import success_response
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article 

router = APIRouter(prefix="/api/products", tags=["products"])

@router.get("")
def get_products(session: Session = Depends(get_session)) -> dict:
    stmt = (
        select(AnalysisResult, Article)
        .join(Article, Article.id == AnalysisResult.article_id)
        .where(
            Article.status == ArticleProcessingStatus.STORED.value,
            displayable_product_clause(AnalysisResult.product),
        )
        .order_by(AnalysisResult.product.asc(), Article.publish_time.desc())
    )

    grouped: dict[str, list[dict]] = {}

    for result, article in session.execute(stmt).all():
        product = result.product
        date_source = article.publish_time or result.analysis_time

        if product not in grouped:
            grouped[product] = []
        grouped[product].append(
            {
                "article_id": article.id,
                "result_id": result.id,
                "direction": result.direction,
                "confidence": result.confidence,
                "company": article.company or article.source or "",
                "date": date_source.date().isoformat() if date_source else "",
                "reason": result.reason,
                "contract": result.contract,
                "need_manual_review": result.need_manual_review,
            }
        )

    data = []
    for product, predictions in grouped.items():
        data.append({
            "product": product,
            "predictions": predictions,
        })

    return success_response(data)
