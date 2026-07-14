"""Product catalog and product resolution review endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from back_end.app.api.schemas import ProductAliasReviewRequest, ProductResolutionConfirmRequest, datetime_to_iso
from back_end.app.core.database import get_session
from back_end.app.core.responses import success_response
from back_end.app.repositories import ProductRepository
from data_proccessing.catalog import PRODUCT_CATALOG, get_product

router = APIRouter(tags=["product-review"])


@router.get("/api/product-catalog")
def get_product_catalog() -> dict:
    return success_response([
        {
            "product_key": item.product_key,
            "display_name": item.display_name,
            "official_name": item.official_name,
            "exchange": item.exchange,
            "symbol": item.symbol,
            "product_group": item.group,
            "active": item.active,
        }
        for item in PRODUCT_CATALOG
        if item.active
    ])


@router.get("/api/product-resolutions")
def list_product_resolutions(
    status: str = "pending",
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    rows = ProductRepository(session).list_resolutions(status=status, limit=limit)
    return success_response([_serialize_resolution(item) for item in rows])


@router.post("/api/product-resolutions/{resolution_id}/confirm")
def confirm_product_resolution(
    resolution_id: int,
    request: ProductResolutionConfirmRequest,
    session: Session = Depends(get_session),
) -> dict:
    item = ProductRepository(session).confirm_resolution(
        resolution_id,
        product_key=request.product_key,
        reviewed_by=request.reviewed_by,
        note=request.note,
    )
    session.commit()
    payload = _serialize_resolution(item)
    payload["reanalysis_required"] = True
    return success_response(payload)


@router.get("/api/product-aliases")
def list_product_aliases(
    status: str = "pending",
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    rows = ProductRepository(session).list_aliases(status=status, limit=limit)
    return success_response([_serialize_alias(item) for item in rows])


@router.post("/api/product-aliases/{alias_id}/approve")
def approve_product_alias(
    alias_id: int,
    request: ProductAliasReviewRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    payload = request or ProductAliasReviewRequest()
    item = ProductRepository(session).review_alias(
        alias_id, approve=True, reviewed_by=payload.reviewed_by, note=payload.note
    )
    session.commit()
    return success_response(_serialize_alias(item))


@router.post("/api/product-aliases/{alias_id}/reject")
def reject_product_alias(
    alias_id: int,
    request: ProductAliasReviewRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    payload = request or ProductAliasReviewRequest()
    item = ProductRepository(session).review_alias(
        alias_id, approve=False, reviewed_by=payload.reviewed_by, note=payload.note
    )
    session.commit()
    return success_response(_serialize_alias(item))


def _serialize_resolution(item) -> dict:
    suggestion = get_product(item.suggested_product_key)
    resolved = get_product(item.resolved_product_key)
    return {
        "id": item.id,
        "article_id": item.article_id,
        "article_title": item.article.title if item.article else "",
        "raw_name": item.raw_name,
        "excerpt": item.excerpt,
        "suggested_product_key": item.suggested_product_key,
        "suggested_product": suggestion.display_name if suggestion else None,
        "resolved_product_key": item.resolved_product_key,
        "resolved_product": resolved.display_name if resolved else None,
        "confidence": item.confidence,
        "method": item.method,
        "status": item.status,
        "reviewed_by": item.reviewed_by,
        "review_note": item.review_note,
        "created_at": datetime_to_iso(item.created_at),
    }


def _serialize_alias(item) -> dict:
    product = get_product(item.product_key)
    return {
        "id": item.id,
        "alias": item.alias,
        "product_key": item.product_key,
        "product": product.display_name if product else item.product_key,
        "product_group": product.group if product else "",
        "status": item.status,
        "occurrence_count": item.occurrence_count,
        "confidence": item.confidence,
        "reviewed_by": item.reviewed_by,
        "review_note": item.review_note,
        "created_at": datetime_to_iso(item.created_at),
    }
