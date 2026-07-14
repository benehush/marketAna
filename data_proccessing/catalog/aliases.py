"""Alias indexes derived from the local standard catalog."""

from __future__ import annotations

from collections import defaultdict

from data_proccessing.catalog.catalog import PRODUCT_CATALOG
from data_proccessing.instrument_mapping.seed_catalog import normalize_alias


def alias_to_product_keys() -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for item in PRODUCT_CATALOG:
        aliases = (item.display_name, item.official_name, *item.aliases, item.symbol)
        for alias in aliases:
            normalized = normalize_alias(alias)
            if normalized:
                index[normalized].add(item.product_key)
    return dict(index)


def symbol_to_product_key() -> dict[str, str]:
    return {item.symbol.upper(): item.product_key for item in PRODUCT_CATALOG if item.symbol}
