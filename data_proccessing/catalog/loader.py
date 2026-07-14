"""Catalog loading and validation helpers."""

from __future__ import annotations

from data_proccessing.catalog.catalog import PRODUCT_CATALOG, ProductDefinition, validate_catalog


def load_catalog() -> tuple[ProductDefinition, ...]:
    validate_catalog()
    return PRODUCT_CATALOG


def catalog_as_dicts() -> list[dict[str, object]]:
    return [
        {
            "product_key": item.product_key,
            "display_name": item.display_name,
            "official_name": item.official_name,
            "exchange": item.exchange,
            "symbol": item.symbol,
            "group": item.group,
            "aliases": list(item.aliases),
            "active": item.active,
        }
        for item in load_catalog()
    ]
