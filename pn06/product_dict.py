"""Product catalog compatibility view and deterministic product matcher."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Iterable, Mapping

from pn06.product_catalog import PRODUCT_CATALOG, ProductDefinition


PRODUCT_DICT: dict[str, list[str]] = {
    item.display_name: list(dict.fromkeys((item.display_name, item.official_name, *item.aliases, item.symbol)))
    for item in PRODUCT_CATALOG
}

_ALIAS_NEGATIVE_PREFIXES: dict[str, tuple[str, ...]] = {
    "豆油": ("美",),
    "原油": ("美",),
    "沪铜": ("LME", "伦"),
    "沪铝": ("LME", "伦"),
    "沪锌": ("LME", "伦"),
    "沪铅": ("LME", "伦"),
    "沪镍": ("LME", "伦"),
    "沪锡": ("LME", "伦"),
    "黄金": ("COMEX",),
    "白银": ("COMEX",),
}


@dataclass(frozen=True, slots=True)
class ProductMatch:
    product_key: str
    product: str
    alias: str
    start: int
    end: int
    source: str


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return re.sub(r"[\s【】\[\]（）()：:]+", "", normalized)


class ProductMatcher:
    """Resolve catalog products using deterministic precedence and span overlap rules."""

    def __init__(
        self,
        *,
        dynamic_aliases: Mapping[str, str] | None = None,
        manual_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._definitions = {item.product_key: item for item in PRODUCT_CATALOG}
        self._manual = self._prepare_external_aliases(manual_overrides or {}, "manual")
        self._dynamic = self._prepare_external_aliases(dynamic_aliases or {}, "dynamic")
        self._builtin: list[tuple[str, ProductDefinition, str]] = []
        for item in PRODUCT_CATALOG:
            for alias in dict.fromkeys((item.display_name, item.official_name, *item.aliases)):
                self._builtin.append((alias, item, "builtin"))

    def _prepare_external_aliases(
        self,
        aliases: Mapping[str, str],
        source: str,
    ) -> list[tuple[str, ProductDefinition, str]]:
        prepared: list[tuple[str, ProductDefinition, str]] = []
        for alias, product_key in aliases.items():
            item = self._definitions.get(product_key.upper())
            if alias.strip() and item:
                prepared.append((alias.strip(), item, source))
        return prepared

    def find_matches(self, text: str) -> list[ProductMatch]:
        if not text:
            return []
        candidates: list[tuple[int, int, int, ProductMatch]] = []
        # Lower priority value wins when start and matched length are equal.
        for priority, aliases in enumerate((self._manual, self._contract_aliases(), self._dynamic, self._builtin)):
            for alias, item, source in aliases:
                for match in _iter_text_matches(text, alias, item, contract=(source == "contract")):
                    product_match = ProductMatch(
                        product_key=item.product_key,
                        product=item.display_name,
                        alias=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        source=source,
                    )
                    candidates.append((match.start(), -(match.end() - match.start()), priority, product_match))

        accepted: list[ProductMatch] = []
        for _start, _negative_length, _priority, candidate in sorted(candidates):
            if any(candidate.start < item.end and item.start < candidate.end for item in accepted):
                continue
            accepted.append(candidate)
        return sorted(accepted, key=lambda item: (item.start, item.end))

    def detect_products(self, text: str) -> dict[str, int]:
        found: dict[str, int] = {}
        for match in self.find_matches(text):
            found[match.product] = found.get(match.product, 0) + 1
        return dict(sorted(found.items(), key=lambda item: item[1], reverse=True))

    def resolve_name(self, raw_name: str) -> ProductDefinition | None:
        compact = normalize_alias(raw_name)
        if not compact:
            return None
        exact = [
            match
            for match in self.find_matches(raw_name)
            if normalize_alias(match.alias) == compact
        ]
        if len({item.product_key for item in exact}) != 1:
            return None
        return self._definitions[exact[0].product_key]

    @staticmethod
    def _contract_aliases() -> list[tuple[str, ProductDefinition, str]]:
        return [
            (item.symbol, item, "contract")
            for item in PRODUCT_CATALOG
            if item.symbol
        ]


_DEFAULT_MATCHER = ProductMatcher()


def get_alias_map() -> dict[str, str]:
    """Return the legacy alias -> display name view."""
    result: dict[str, str] = {}
    for item in PRODUCT_CATALOG:
        for alias in dict.fromkeys((item.display_name, item.official_name, *item.aliases, item.symbol)):
            result[alias.casefold()] = item.display_name
    return result


def detect_products(text: str) -> dict[str, int]:
    return _DEFAULT_MATCHER.detect_products(text)


def count_alias_matches(text: str, alias: str, *, canonical: str | None = None) -> int:
    return sum(1 for _ in iter_alias_matches(text, alias, canonical=canonical))


def iter_alias_matches(text: str, alias: str, *, canonical: str | None = None) -> Iterable[re.Match[str]]:
    if not text or not alias.strip():
        return
    display = canonical or get_alias_map().get(alias.casefold()) or ""
    item = next((candidate for candidate in PRODUCT_CATALOG if candidate.display_name == display), None)
    for match in _iter_text_matches(text, alias, item, contract=False):
        yield match


def product_mentioned(text: str, product: str) -> bool:
    return product in detect_products(text)


def get_primary_product(text: str) -> str | None:
    products = detect_products(text)
    return next(iter(products), None)


def _iter_text_matches(
    text: str,
    alias: str,
    item: ProductDefinition | None,
    *,
    contract: bool,
) -> Iterable[re.Match[str]]:
    alias = alias.strip()
    if not alias:
        return
    pattern = re.escape(alias)
    if contract:
        # A bare one-letter symbol is too ambiguous; all symbols are also
        # recognized in concrete contracts such as T2609 or A2509.
        if len(alias) == 1:
            pattern = rf"(?<![A-Za-z0-9]){pattern}\d{{3,4}}(?![A-Za-z0-9])"
        else:
            pattern = rf"(?<![A-Za-z0-9]){pattern}(?:\d{{3,4}})?(?![A-Za-z0-9])"
    elif re.fullmatch(r"[A-Za-z0-9]+", alias):
        pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        if item and _is_excluded_alias_match(text, match.start(), item.display_name):
            continue
        yield match


def _is_excluded_alias_match(text: str, start: int, product: str) -> bool:
    prefixes = _ALIAS_NEGATIVE_PREFIXES.get(product, ())
    if not prefixes:
        return False
    max_length = max(len(prefix) for prefix in prefixes)
    before = text[max(0, start - max_length):start].casefold()
    return any(before.endswith(prefix.casefold()) for prefix in prefixes)
