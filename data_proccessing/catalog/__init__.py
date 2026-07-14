"""Self-contained standard futures catalog for data processing."""

from data_proccessing.catalog.catalog import (
    PRODUCT_CATALOG,
    ProductDefinition,
    get_product,
    product_for_symbol,
    product_group,
    product_key_for_name,
    validate_catalog,
)
from data_proccessing.catalog.loader import catalog_as_dicts, load_catalog

__all__ = [
    "PRODUCT_CATALOG",
    "ProductDefinition",
    "get_product",
    "product_for_symbol",
    "product_group",
    "product_key_for_name",
    "validate_catalog",
    "catalog_as_dicts",
    "load_catalog",
]
