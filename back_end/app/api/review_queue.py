"""Article-level manual review work queue."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from back_end.app.core.database import get_session
from back_end.app.core.exceptions import AppException, ErrorCode
from back_end.app.core.responses import success_response
from back_end.app.repositories.review_queue import QUEUE_TABS, ReviewQueueRepository

router = APIRouter(prefix="/api/review-queue", tags=["manual-review"])


@router.get("")
def list_review_queue(tab: str = "pending", company: str | None = None,
                      product_key: str | None = None, reason: str | None = None,
                      keyword: str | None = None, missing_evidence: bool = False,
                      sort: str | None = None, page: int = Query(default=1, ge=1),
                      page_size: int = Query(default=20, ge=1, le=100),
                      session: Session = Depends(get_session)) -> dict:
    if tab not in QUEUE_TABS:
        raise AppException(ErrorCode.VALIDATION_ERROR, "Invalid review queue tab", {"tab": tab})
    if sort not in {None, "pending_count", "oldest", "newest"}:
        raise AppException(ErrorCode.VALIDATION_ERROR, "Invalid review queue sort", {"sort": sort})
    return success_response(ReviewQueueRepository(session).list_queue(
        tab=tab, company=company, product_key=product_key, reason=reason,
        keyword=keyword, missing_evidence=missing_evidence, sort=sort,
        page=page, page_size=page_size,
    ))
