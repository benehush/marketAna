"""Extract short, traceable direction signals from raw text."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

from data_proccessing.instrument_mapping.runtime import LexiconMatch
from data_proccessing.models import DirectionSignal
from data_proccessing.sections import ProductSection, build_product_sections, section_for_position
from data_proccessing.signals.context import context_flags
from data_proccessing.signals.patterns import COMPILED_PATTERNS, PATTERN_WEIGHTS


def extract_signals(
    text: str,
    matches: Iterable[LexiconMatch],
    *,
    context_window: int = 80,
) -> list[DirectionSignal]:
    all_matches = tuple(matches)
    sections = build_product_sections(text, all_matches)
    signals: list[DirectionSignal] = []
    for section in sections:
        for product_key in section.product_keys:
            heading_match = next(
                (
                    match
                    for match in all_matches
                    if match.product_key == product_key
                    and section.heading_start <= match.start < section.heading_end
                ),
                None,
            )
            extracted = _extract_span(
                text,
                start_offset=section.body_start,
                end_offset=section.body_end,
                product_key=product_key,
                raw_alias=heading_match.alias if heading_match else product_key,
            )
            if len(section.concrete_product_keys) > 1 and product_key in section.concrete_product_keys:
                extracted = [
                    signal
                    for signal in extracted
                    if _shared_signal_owner(text, signal.start, signal.end, section, all_matches)
                    == product_key
                ]
            signals.extend(extracted)

    for product_match in all_matches:
        if any(
            section.heading_start <= product_match.start < section.heading_end
            and product_match.product_key in section.product_keys
            for section in sections
        ):
            # Heading aliases define ownership but must not open an additional
            # free-form context window across the previous/next section.
            continue
        section = section_for_position(sections, product_match.start)
        if section is not None:
            if product_match.product_key in section.product_keys:
                # The complete owned section was already extracted above.
                continue
        window_start = max(0, product_match.start - context_window)
        window_end = min(len(text), product_match.end + context_window)
        if section is not None:
            window_start = max(window_start, section.body_start)
            window_end = min(window_end, section.body_end)
        extracted = _extract_span(
            text,
            start_offset=window_start,
            end_offset=window_end,
            product_key=product_match.product_key,
            raw_alias=product_match.alias,
        )
        # A fallback window may contain a neighbouring product's signal. Keep
        # only signals whose nearest clause/sentence anchor is this product.
        signals.extend(
            signal
            for signal in extracted
            if _context_signal_owner(text, signal, product_match, all_matches, window_start, window_end)
            == product_match.product_key
        )
    return _deduplicate(signals)


def _context_signal_owner(
    text: str,
    signal: DirectionSignal,
    product_match: LexiconMatch,
    matches: tuple[LexiconMatch, ...],
    lower: int,
    upper: int,
) -> str | None:
    anchors = tuple(
        match
        for match in matches
        if lower <= match.start < upper and match.end > lower
    )
    clause = _bounded_span(text, signal.start, signal.end, lower, upper, "，,；;。！？!?\n")
    owner = _nearest_unique_owner(signal.start, anchors, *clause)
    if owner is not None:
        return owner
    sentence = _bounded_span(text, signal.start, signal.end, lower, upper, "。！？!?\n")
    return _nearest_unique_owner(signal.start, anchors, *sentence)


def _shared_signal_owner(
    text: str,
    signal_start: int,
    signal_end: int,
    section: ProductSection,
    matches: tuple[LexiconMatch, ...],
) -> str | None:
    keys = section.concrete_product_keys
    anchors = tuple(
        match
        for match in matches
        if match.product_key in keys and section.body_start <= match.start < section.body_end
    )
    clause = _bounded_span(text, signal_start, signal_end, section.body_start, section.body_end, "，,；;。！？!?\n")
    owner = _nearest_unique_owner(signal_start, anchors, *clause)
    if owner is not None:
        return owner
    sentence = _bounded_span(text, signal_start, signal_end, section.body_start, section.body_end, "。！？!?\n")
    return _nearest_unique_owner(signal_start, anchors, *sentence)


def _nearest_unique_owner(
    signal_start: int,
    matches: tuple[LexiconMatch, ...],
    start: int,
    end: int,
) -> str | None:
    scoped = [match for match in matches if start <= match.start < end]
    if not scoped:
        return None
    preceding = [match for match in scoped if match.end <= signal_start]
    pool = preceding or scoped
    distances = [
        (abs(signal_start - (match.end if match.end <= signal_start else match.start)), match.product_key)
        for match in pool
    ]
    best_distance = min(distance for distance, _key in distances)
    owners = {key for distance, key in distances if distance == best_distance}
    return next(iter(owners)) if len(owners) == 1 else None


def _bounded_span(
    text: str,
    signal_start: int,
    signal_end: int,
    lower: int,
    upper: int,
    delimiters: str,
) -> tuple[int, int]:
    previous = max(text.rfind(mark, lower, signal_start) for mark in delimiters)
    start = lower if previous < 0 else previous + 1
    endings = [text.find(mark, signal_end, upper) for mark in delimiters]
    endings = [position for position in endings if position >= 0]
    end = min(endings) + 1 if endings else upper
    return start, end


def _extract_span(
    text: str,
    *,
    start_offset: int,
    end_offset: int,
    product_key: str,
    raw_alias: str,
) -> list[DirectionSignal]:
    signals: list[DirectionSignal] = []
    window = text[start_offset:end_offset]
    for signal_type, direction, _label, pattern in COMPILED_PATTERNS:
        for found in pattern.finditer(window):
            start = start_offset + found.start()
            end = start_offset + found.end()
            flags = context_flags(text, start, end)
            phrase = found.group(0)
            evidence = text[max(0, start - 35):min(len(text), end + 35)].replace("\n", " ").strip()
            signal_id = hashlib.sha1(
                f"{product_key}|{start}|{end}|{direction}|{phrase}".encode("utf-8")
            ).hexdigest()[:16]
            signals.append(
                DirectionSignal(
                    signal_id=signal_id,
                    product_key=product_key,
                    raw_alias=raw_alias,
                    direction=direction,  # type: ignore[arg-type]
                    signal_type=signal_type,
                    phrase=phrase,
                    value=_numeric_value(phrase),
                    confidence=max(0.05, min(1.0, _signal_factor(flags))),
                    start=start,
                    end=end,
                    evidence_text=evidence,
                    context_flags=flags,
                )
            )
    return signals


def _numeric_value(phrase: str) -> float | None:
    match = re.search(r"[+-]?\d+(?:\.\d+)?", phrase)
    return float(match.group(0)) if match else None


def _signal_factor(flags: tuple[str, ...]) -> float:
    factor = 1.0
    if "negated" in flags:
        factor *= 0.35
    if "conditional" in flags:
        factor *= 0.70
    if "historical" in flags:
        factor *= 0.50
    if "risk_context" in flags:
        factor *= 0.75
    if "after_turn" in flags:
        factor *= 0.75
    return factor


def _deduplicate(signals: list[DirectionSignal]) -> list[DirectionSignal]:
    unique: dict[tuple[str | None, int, int, str], DirectionSignal] = {}
    for signal in signals:
        key = (signal.product_key, signal.start, signal.end, signal.direction)
        previous = unique.get(key)
        if previous is None or signal.confidence > previous.confidence:
            unique[key] = signal

    # A domain-specific phrase such as “库存下降” must win over the shorter
    # generic direction word “下降” occurring inside the same span.
    ordered = sorted(unique.values(), key=lambda item: (-(item.end - item.start), item.start))
    accepted: list[DirectionSignal] = []
    for signal in ordered:
        overlaps = [
            item for item in accepted
            if item.product_key == signal.product_key
            and signal.start < item.end
            and item.start < signal.end
        ]
        if overlaps:
            continue
        accepted.append(signal)
    return sorted(accepted, key=lambda item: (item.product_key or "", item.start, item.end))
