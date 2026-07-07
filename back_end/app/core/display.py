"""Shared frontend-display predicates."""

from typing import Any

from sqlalchemy import and_, func


UNKNOWN_PRODUCT = "未知"


def is_displayable_product(product: str | None) -> bool:
    """Return whether an analysis product should be exposed by frontend APIs."""
    normalized = (product or "").strip()
    return bool(normalized) and normalized != UNKNOWN_PRODUCT


def is_displayable_analysis_result(result: Any) -> bool:
    return is_displayable_product(getattr(result, "product", None))


def displayable_product_clause(product_column: Any):
    product = func.trim(product_column)
    return and_(product != "", product != UNKNOWN_PRODUCT)
