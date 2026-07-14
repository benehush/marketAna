"""Human review actions for non-formal canonical pipeline outcomes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from back_end.app.api.schemas import CreateManualConclusionRequest, RejectAnalysisReviewRequest
from back_end.app.api.serializers import serialize_analysis_result
from back_end.app.core.database import get_session
from back_end.app.core.responses import success_response
from back_end.app.repositories import ArticleRepository

router = APIRouter(prefix="/api/review-items", tags=["manual-review"])


@router.post("/{review_id}/reject")
def reject_review_item(
    review_id: int,
    request: RejectAnalysisReviewRequest,
    session: Session = Depends(get_session),
) -> dict:
    item = ArticleRepository(session).reject_review_item(
        review_id,
        reviewed_by=request.reviewed_by,
        reason_code=request.reason_code,
        note=request.note,
    )
    session.commit()
    return success_response({"id": item.id, "status": item.status})


@router.post("/{review_id}/conclusion")
def create_manual_conclusion(
    review_id: int,
    request: CreateManualConclusionRequest,
    session: Session = Depends(get_session),
) -> dict:
    result = ArticleRepository(session).create_manual_conclusion(
        review_id,
        direction=request.direction,
        reason=request.reason,
        evidence=request.evidence,
        product_key=request.product_key,
        reviewed_by=request.reviewed_by,
    )
    session.commit()
    return success_response(serialize_analysis_result(result))
