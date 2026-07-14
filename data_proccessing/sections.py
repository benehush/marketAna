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
    context_window: int = 80,
) -> list[tuple[int, int]]:
    matches = tuple(all_matches)
    sections = build_product_sections(text, matches)

    direct = [
        (section.body_start, section.body_end)
        for section in sections
        if product_key in section.product_keys
    ]
    if direct:
        return direct

    # A product that is not named by a bracket heading does not own an entire
    # section. It still needs a deterministic scope for signals and evidence.
    # Previously this returned no scope whenever another product was present,
    # so signals could be extracted while every evidence sentence was dropped.
    own_matches = tuple(product_matches)
    spans: list[tuple[int, int]] = []
    for match in own_matches:
        start = max(0, match.start - max(0, context_window))
        end = min(len(text), match.end + max(0, context_window))
        section = section_for_position(sections, match.start)
        if section is not None:
            # Never let a fallback window cross a real chapter boundary.
            start = max(start, section.body_start)
            end = min(end, section.body_end)
        if start < end:
            spans.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


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
