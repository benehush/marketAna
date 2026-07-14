"""Shared bracket-heading section boundaries and product ownership."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from data_proccessing.instrument_mapping.runtime import LexiconMatch


HEADING_PATTERN = re.compile(r"【\s*([^】\n]{1,40}?)\s*】")


@dataclass(frozen=True, slots=True)
class ProductSection:
    heading_start: int
    heading_end: int
    body_start: int
    body_end: int
    product_keys: frozenset[str]

    @property
    def concrete_product_keys(self) -> frozenset[str]:
        return frozenset(key for key in self.product_keys if not key.startswith("GROUP."))


def build_product_sections(text: str, matches: Iterable[LexiconMatch]) -> tuple[ProductSection, ...]:
    all_matches = tuple(matches)
    headings = tuple(HEADING_PATTERN.finditer(text))
    sections: list[ProductSection] = []
    for index, heading in enumerate(headings):
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        keys = frozenset(
            match.product_key
            for match in all_matches
            if heading.start() <= match.start < heading.end()
        )
        sections.append(
            ProductSection(
                heading_start=heading.start(),
                heading_end=heading.end(),
                body_start=heading.end(),
                body_end=body_end,
                product_keys=keys,
            )
        )
    return tuple(sections)


def section_for_position(sections: Iterable[ProductSection], position: int) -> ProductSection | None:
    return next(
        (section for section in sections if section.body_start <= position < section.body_end),
        None,
    )


def product_section_spans(
    text: str,
    *,
    product_key: str,
    product_matches: Iterable[LexiconMatch],
    all_matches: Iterable[LexiconMatch],
) -> list[tuple[int, int]]:
    matches = tuple(all_matches)
    sections = build_product_sections(text, matches)
    if not sections:
        body_keys = {match.product_key for match in matches if match.start < len(text)}
        return [(0, len(text))] if body_keys == {product_key} else []

    direct = [
        (section.body_start, section.body_end)
        for section in sections
        if product_key in section.product_keys
    ]
    if direct:
        return direct

    own_matches = tuple(product_matches)
    return [
        (section.body_start, section.body_end)
        for section in sections
        if not section.product_keys
        and any(section.body_start <= match.start < section.body_end for match in own_matches)
    ]


def is_related_mention_only(
    product_key: str,
    product_matches: Iterable[LexiconMatch],
    sections: Iterable[ProductSection],
) -> bool:
    """True when every mention belongs to another concrete product's section."""
    matches = tuple(product_matches)
    section_rows = tuple(sections)
    if not matches:
        return False
    for match in matches:
        section = section_for_position(section_rows, match.start)
        if section is None:
            return False
        if product_key in section.product_keys:
            return False
        if not section.concrete_product_keys:
            return False
    return True
