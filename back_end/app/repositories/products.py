"""Persistence for product resolution and learned alias review."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from back_end.app.core.exceptions import AppException, ErrorCode
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, ArticleProductSegment, ProductAlias, ProductResolution
from back_end.app.repositories.base import BaseRepository
from pn06.product_catalog import get_product
from pn06.product_dict import ProductMatcher, normalize_alias


class ProductRepository(BaseRepository):
    def approved_aliases(self) -> dict[str, str]:
        rows = self.session.scalars(
            select(ProductAlias).where(ProductAlias.status == "approved")
        ).all()
        return {item.alias: item.product_key for item in rows}

    def article_overrides(self, article_id: int) -> dict[str, str]:
        rows = self.session.scalars(
            select(ProductResolution).where(
                ProductResolution.article_id == article_id,
                ProductResolution.status.in_(("confirmed", "auto_resolved")),
                ProductResolution.resolved_product_key.is_not(None),
            )
        ).all()
        return {
            item.raw_name: item.resolved_product_key or ""
            for item in rows
            if item.raw_name and item.resolved_product_key
        }

    def article_fingerprint_overrides(self, article_id: int) -> dict[str, str]:
        rows = self.session.scalars(
            select(ProductResolution).where(
                ProductResolution.article_id == article_id,
                ProductResolution.status.in_(("confirmed", "auto_resolved")),
                ProductResolution.resolved_product_key.is_not(None),
            )
        ).all()
        return {
            item.block_fingerprint: item.resolved_product_key or ""
            for item in rows
            if item.resolved_product_key
        }

    def matcher(self, article_id: int | None = None) -> ProductMatcher:
        return ProductMatcher(
            dynamic_aliases=self.approved_aliases(),
            manual_overrides=self.article_overrides(article_id) if article_id is not None else {},
        )

    def sync_unknown_resolutions(self, article_id: int, blocks: list[dict[str, Any]]) -> list[ProductResolution]:
        existing = {
            item.block_fingerprint: item
            for item in self.session.scalars(
                select(ProductResolution).where(ProductResolution.article_id == article_id)
            ).all()
        }
        seen: set[str] = set()
        saved: list[ProductResolution] = []
        for block in blocks:
            fingerprint = str(block["block_fingerprint"])
            seen.add(fingerprint)
            item = existing.get(fingerprint)
            if item is None:
                item = ProductResolution(article_id=article_id, block_fingerprint=fingerprint)
                self.session.add(item)
            item.segment_index = int(block.get("segment_index") or 0)
            item.raw_name = str(block.get("raw_name") or "")[:255]
            item.normalized_raw_name = normalize_alias(item.raw_name)[:255]
            item.excerpt = str(block.get("excerpt") or "")[:1000]
            item.start_char = block.get("start_char")
            item.end_char = block.get("end_char")
            if item.status not in {"confirmed", "auto_resolved"}:
                item.status = "pending"
                item.method = "unknown"
            saved.append(item)

        for fingerprint, item in existing.items():
            if fingerprint not in seen and item.status == "pending":
                item.status = "obsolete"
        self.session.flush()
        return saved

    def apply_llm_resolution(
        self,
        resolution: ProductResolution,
        *,
        product_key: str | None,
        confidence: float,
        auto_threshold: float,
    ) -> bool:
        product = get_product(product_key)
        resolution.suggested_product_key = product.product_key if product else None
        resolution.confidence = max(0.0, min(1.0, float(confidence)))
        resolution.method = "llm"
        if product is None or resolution.confidence < auto_threshold:
            resolution.status = "pending"
            resolution.resolved_product_key = None
            self.session.flush()
            return False

        resolution.status = "auto_resolved"
        resolution.resolved_product_key = product.product_key
        self._update_segment(resolution, product.product_key, "llm", resolution.confidence)
        self.queue_alias(
            resolution.raw_name,
            product.product_key,
            source_resolution_id=resolution.id,
            confidence=resolution.confidence,
        )
        self.session.flush()
        return True

    def list_resolutions(self, status: str = "pending", limit: int = 100) -> list[ProductResolution]:
        return list(
            self.session.scalars(
                select(ProductResolution)
                .where(ProductResolution.status == status)
                .order_by(ProductResolution.created_at.asc(), ProductResolution.id.asc())
                .limit(limit)
            ).all()
        )

    def pending_resolutions_for_article(self, article_id: int) -> list[ProductResolution]:
        return list(
            self.session.scalars(
                select(ProductResolution)
                .where(
                    ProductResolution.article_id == article_id,
                    ProductResolution.status == "pending",
                )
                .order_by(ProductResolution.segment_index.asc(), ProductResolution.id.asc())
            ).all()
        )

    def confirm_resolution(
        self,
        resolution_id: int,
        *,
        product_key: str,
        reviewed_by: str | None = None,
        note: str | None = None,
    ) -> ProductResolution:
        resolution = self.session.get(ProductResolution, resolution_id)
        if resolution is None:
            raise AppException(ErrorCode.NOT_FOUND, "Product resolution not found", status_code=404)
        product = get_product(product_key)
        if product is None:
            raise AppException(
                ErrorCode.VALIDATION_ERROR,
                "Unknown product_key",
                detail={"product_key": product_key},
            )
        resolution.suggested_product_key = resolution.suggested_product_key or product.product_key
        resolution.resolved_product_key = product.product_key
        resolution.confidence = 1.0
        resolution.method = "manual"
        resolution.status = "confirmed"
        resolution.reviewed_by = reviewed_by
        resolution.review_note = note
        resolution.reviewed_at = datetime.now()
        self._update_segment(resolution, product.product_key, "manual", 1.0)
        self.queue_alias(
            resolution.raw_name,
            product.product_key,
            source_resolution_id=resolution.id,
            confidence=1.0,
        )
        # Preserve manually curated predictions; all automatic rows are rebuilt.
        self.session.execute(
            delete(AnalysisResult).where(
                AnalysisResult.article_id == resolution.article_id,
                AnalysisResult.analysis_method != "manual",
            )
        )
        from back_end.app.repositories.articles import ArticleRepository

        ArticleRepository(self.session).update_status(
            resolution.article_id, ArticleProcessingStatus.CLEANED
        )
        self.session.flush()
        return resolution

    def queue_alias(
        self,
        alias: str,
        product_key: str,
        *,
        source_resolution_id: int | None,
        confidence: float,
    ) -> ProductAlias | None:
        alias = (alias or "").strip().strip("【】")
        normalized = normalize_alias(alias)
        product = get_product(product_key)
        if not normalized or product is None:
            return None
        builtin = ProductMatcher().resolve_name(alias)
        if builtin and builtin.product_key == product.product_key:
            return None
        item = self.session.scalar(
            select(ProductAlias).where(
                ProductAlias.normalized_alias == normalized,
                ProductAlias.product_key == product.product_key,
            )
        )
        if item is None:
            item = ProductAlias(
                alias=alias,
                normalized_alias=normalized,
                product_key=product.product_key,
                source_resolution_id=source_resolution_id,
                confidence=max(0.0, min(1.0, confidence)),
            )
            self.session.add(item)
        else:
            item.occurrence_count += 1
            item.confidence = max(item.confidence, max(0.0, min(1.0, confidence)))
            if item.source_resolution_id is None:
                item.source_resolution_id = source_resolution_id
        self.session.flush()
        return item

    def list_aliases(self, status: str = "pending", limit: int = 100) -> list[ProductAlias]:
        return list(
            self.session.scalars(
                select(ProductAlias)
                .where(ProductAlias.status == status)
                .order_by(ProductAlias.created_at.asc(), ProductAlias.id.asc())
                .limit(limit)
            ).all()
        )

    def review_alias(
        self,
        alias_id: int,
        *,
        approve: bool,
        reviewed_by: str | None = None,
        note: str | None = None,
    ) -> ProductAlias:
        item = self.session.get(ProductAlias, alias_id)
        if item is None:
            raise AppException(ErrorCode.NOT_FOUND, "Product alias not found", status_code=404)
        if approve:
            builtin = ProductMatcher().resolve_name(item.alias)
            if builtin is not None and builtin.product_key != item.product_key:
                raise AppException(
                    ErrorCode.VALIDATION_ERROR,
                    "Alias conflicts with the built-in product catalog",
                    detail={"alias": item.alias, "product_key": builtin.product_key},
                    status_code=409,
                )
            conflict = self.session.scalar(
                select(ProductAlias).where(
                    ProductAlias.normalized_alias == item.normalized_alias,
                    ProductAlias.status == "approved",
                    ProductAlias.product_key != item.product_key,
                )
            )
            if conflict is not None:
                raise AppException(
                    ErrorCode.VALIDATION_ERROR,
                    "Alias is already approved for another product",
                    detail={"alias": item.alias, "product_key": conflict.product_key},
                    status_code=409,
                )
        item.status = "approved" if approve else "rejected"
        item.reviewed_by = reviewed_by
        item.review_note = note
        item.reviewed_at = datetime.now()
        self.session.flush()
        return item

    def _update_segment(
        self,
        resolution: ProductResolution,
        product_key: str,
        method: str,
        confidence: float,
    ) -> None:
        product = get_product(product_key)
        if product is None:
            return
        segment = self.session.scalar(
            select(ArticleProductSegment).where(
                ArticleProductSegment.article_id == resolution.article_id,
                ArticleProductSegment.segment_index == resolution.segment_index,
            )
        )
        if segment is None:
            return
        segment.product = product.display_name
        segment.product_key = product.product_key
        segment.raw_product_name = resolution.raw_name
        segment.resolution_method = method
        segment.resolution_confidence = confidence
        segment.confidence = confidence
