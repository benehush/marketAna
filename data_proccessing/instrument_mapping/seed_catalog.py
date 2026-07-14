"""Seed catalog adapter.

This module intentionally imports only the static product catalog.  It does not
call the legacy matcher, cleaner, segmenter, or rule engine.
"""

from __future__ import annotations

from collections import defaultdict
import re
import unicodedata

from data_proccessing.catalog import PRODUCT_CATALOG

from data_proccessing.instrument_mapping.models import SeedInstrument


MANUAL_ALIAS_SEEDS: dict[str, tuple[str, ...]] = {
    "DCE.L": ("PE",),
    "INE.EC": ("欧集线",),
}

NEGATIVE_CONTEXTS_BY_KEY: dict[str, tuple[str, ...]] = {
    "SHFE.CU": ("LME", "伦"),
    "SHFE.AL": ("LME", "伦"),
    "SHFE.ZN": ("LME", "伦"),
    "SHFE.PB": ("LME", "伦"),
    "SHFE.NI": ("LME", "伦"),
    "SHFE.SN": ("LME", "伦"),
    "SHFE.AU": ("COMEX",),
    "SHFE.AG": ("COMEX",),
    "DCE.Y": ("美",),
    "INE.SC": ("美", "WTI", "BRENT", "Brent"),
}


def load_seed_instruments() -> tuple[SeedInstrument, ...]:
    instruments: list[SeedInstrument] = []
    for item in PRODUCT_CATALOG:
        aliases = (
            item.display_name,
            item.official_name,
            *item.aliases,
            *(MANUAL_ALIAS_SEEDS.get(item.product_key, ())),
        )
        if item.symbol:
            aliases = (*aliases, item.symbol)
        instruments.append(
            SeedInstrument(
                product_key=item.product_key,
                canonical=item.display_name,
                official_name=item.official_name,
                exchange=item.exchange,
                symbol=item.symbol,
                group=item.group,
                seed_aliases=tuple(dict.fromkeys(alias for alias in aliases if alias.strip())),
            )
        )
    return tuple(instruments)


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    normalized = re.sub(r"[\s\u200b-\u200d\ufeff【】\[\]（）(){}<>：:、,，;；/\\\"'“”‘’`]+", "", normalized)
    return normalized


def display_alias(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().strip("【】[]（）(){}<>：:、,，;；")


def build_alias_index(seeds: tuple[SeedInstrument, ...]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for item in seeds:
        for alias in item.seed_aliases:
            normalized = normalize_alias(alias)
            if normalized:
                index[normalized].add(item.product_key)
    return dict(index)


def build_symbol_index(seeds: tuple[SeedInstrument, ...]) -> dict[str, str]:
    return {item.symbol.upper(): item.product_key for item in seeds if item.symbol}
