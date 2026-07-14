from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from back_end.app.api.schemas import ConfirmResultRequest, datetime_to_iso
from back_end.app.api.serializers import serialize_analysis_result, serialize_manual_confirmation
from back_end.app.core.database import get_session
from back_end.app.core.display import formal_analysis_clause
from back_end.app.core.exceptions import AppException, ErrorCode
from back_end.app.core.responses import success_response
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article
from back_end.app.repositories import ArticleRepository

router = APIRouter(prefix="/api/results", tags=["results"])


@router.get("/{result_id}")
def get_result_detail(
    result_id: int,
    session: Session = Depends(get_session),
) -> dict:
    result = session.scalar(
        select(AnalysisResult)
        .join(Article, Article.id == AnalysisResult.article_id)
        .options(
            selectinload(AnalysisResult.article).selectinload(Article.text),
            selectinload(AnalysisResult.article).selectinload(Article.product_segments),
        )
        .where(
            AnalysisResult.id == result_id,
            Article.status == ArticleProcessingStatus.STORED.value,
            formal_analysis_clause(AnalysisResult),
        )
    )
    if result is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="Analysis result not found",
            detail={"result_id": result_id},
            status_code=404,
        )

    article = result.article
    return success_response({
        "result": serialize_analysis_result(
            result,
            article_text=article.text,
            product_segments=article.product_segments,
        ),
        "article": {
            "id": article.id,
            "title": article.title,
            "source": article.source,
            "company": article.company,
            "publish_time": datetime_to_iso(article.publish_time),
            "file_type": article.file_type,
            "has_source": bool(article.file_url),
        },
    })


@router.post("/{result_id}/confirm")
def confirm_result(
    result_id: int,
    request: ConfirmResultRequest,
    session: Session = Depends(get_session),
) -> dict:
    repository = ArticleRepository(session)
    confirmation = repository.confirm_result(
        result_id,
        product=request.product,
        product_key=request.product_key,
        direction=request.direction,
        reason=request.reason,
        confidence=request.confidence,
        confirmed_by=request.confirmed_by,
        note=request.note,
    )
    session.commit()
    return success_response(serialize_manual_confirmation(confirmation))
