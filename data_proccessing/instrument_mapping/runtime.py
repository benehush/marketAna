"""Runtime loading and matching for the generated instrument lexicon."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable, Mapping

from data_proccessing.instrument_mapping.seed_catalog import normalize_alias


@dataclass(frozen=True, slots=True)
class LexiconMatch:
    product_key: str
    display_name: str
    alias: str
    start: int
    end: int
    source: str
    evidence: str


class RuntimeLexicon:
    def __init__(self, entries: Iterable[Mapping[str, object]], dynamic_aliases: Mapping[str, str] | None = None) -> None:
        self._entries = list(entries)
        self._by_alias: dict[str, list[tuple[str, str, str]]] = {}
        self._negative: dict[str, tuple[str, ...]] = {}
        for entry in self._entries:
            key = str(entry.get("product_key") or "")
            display = str(entry.get("canonical") or entry.get("official_name") or key)
            self._negative[key] = tuple(str(item) for item in (entry.get("negative_contexts") or ()))
            aliases = entry.get("aliases") or ()
            for alias in aliases:
                self._add_alias(str(alias), key, display, "lexicon")
        for alias, key in (dynamic_aliases or {}).items():
            self._add_alias(alias, key, self._display_for(key), "approved_review")
        self._aliases = sorted(
            ((normalized, alias, key, display, source) for normalized, items in self._by_alias.items() for alias, key, display, source in items),
            key=lambda item: len(item[1]),
            reverse=True,
        )

    @classmethod
    def from_path(cls, path: str | Path, dynamic_aliases: Mapping[str, str] | None = None) -> "RuntimeLexicon":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("instrument lexicon must be a JSON list")
        return cls(payload, dynamic_aliases=dynamic_aliases)

    def find_matches(self, text: str, *, title: str = "") -> list[LexiconMatch]:
        searchable = text or ""
        matches: list[LexiconMatch] = []
        occupied: list[tuple[int, int]] = []
        for normalized, alias, key, display, source in self._aliases:
            pattern = _alias_pattern(alias)
            for match in re.finditer(pattern, searchable, flags=re.IGNORECASE):
                if _overlaps(match.start(), match.end(), occupied):
                    continue
                if self._negative_context(searchable, match.start(), key):
                    continue
                matches.append(LexiconMatch(key, display, match.group(0), match.start(), match.end(), source, "body_alias"))
                occupied.append((match.start(), match.end()))
        if title:
            for match in self._title_matches(title):
                if not _overlaps(match.start, match.end, [(item.start, item.end) for item in matches]):
                    matches.append(match)
        return sorted(matches, key=lambda item: (item.start, -(item.end - item.start)))

    def products(self, text: str, *, title: str = "") -> dict[str, list[LexiconMatch]]:
        grouped: dict[str, list[LexiconMatch]] = {}
        for match in self.find_matches(text, title=title):
            grouped.setdefault(match.product_key, []).append(match)
        return grouped

    def _add_alias(self, alias: str, key: str, display: str, source: str) -> None:
        normalized = normalize_alias(alias)
        if not normalized or not key:
            return
        self._by_alias.setdefault(normalized, []).append((alias, key, display, source))

    def _display_for(self, key: str) -> str:
        for entry in self._entries:
            if str(entry.get("product_key") or "") == key:
                return str(entry.get("canonical") or entry.get("official_name") or key)
        return key

    def _negative_context(self, text: str, start: int, key: str) -> bool:
        prefix = text[max(0, start - 20):start].casefold()
        return any(str(item).casefold() in prefix for item in self._negative.get(key, ()))

    def _title_matches(self, title: str) -> list[LexiconMatch]:
        result: list[LexiconMatch] = []
        for _normalized, alias, key, display, source in self._aliases:
            match = re.search(_alias_pattern(alias), title, flags=re.IGNORECASE)
            if match:
                result.append(LexiconMatch(key, display, match.group(0), match.start(), match.end(), source, "title_alias"))
        return result


def load_runtime_lexicon(path: str | Path, dynamic_aliases: Mapping[str, str] | None = None) -> RuntimeLexicon:
    return RuntimeLexicon.from_path(path, dynamic_aliases=dynamic_aliases)


def _alias_pattern(alias: str) -> str:
    escaped = re.escape(alias.strip())
    if re.fullmatch(r"[A-Za-z0-9]+", alias.strip()):
        if len(alias.strip()) == 1:
            return rf"(?<![A-Za-z0-9]){escaped}\d{{3,4}}(?![A-Za-z0-9])"
        return rf"(?<![A-Za-z0-9]){escaped}(?:\d{{2,4}})?(?![A-Za-z0-9])"
    return escaped


def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in occupied)
