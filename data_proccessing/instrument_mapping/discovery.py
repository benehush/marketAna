"""One-pass raw-text guided self-discovery for instrument aliases."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata

from data_proccessing.instrument_mapping.models import BuildConfig, CandidateEvidence, Document, SeedInstrument
from data_proccessing.instrument_mapping.progress import ProgressCallback
from data_proccessing.instrument_mapping.seed_catalog import (
    NEGATIVE_CONTEXTS_BY_KEY,
    build_alias_index,
    build_symbol_index,
    display_alias,
    normalize_alias,
)


BRACKET_RE = re.compile(r"[【\[]\s*(?P<alias>[^】\]\n]{1,30})\s*[】\]]")
LABEL_RE = re.compile(r"(?:品种|商品)\s*[：:]\s*(?P<alias>[A-Za-z]{1,8}|[\u4e00-\u9fffA-Za-z0-9（）()]{1,16})")
CHINESE_SUFFIX_RE = re.compile(r"(?P<alias>[\u4e00-\u9fffA-Za-z0-9（）()]{1,16}?)(?:期货|主力|合约)")
CONTRACT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<code>[A-Za-z](?:\s*[A-Za-z]){0,4})\s*(?P<contract>\d{2,4})\s*合约",
    re.IGNORECASE,
)
BARE_SYMBOL_RE = re.compile(r"(?<![A-Za-z0-9])(?P<code>[A-Za-z]{2,5})(?![A-Za-z0-9])")
SPLIT_SYMBOL_RE = re.compile(r"(?<![A-Za-z0-9])(?P<code>[A-Za-z](?:\s+[A-Za-z]){1,4})(?![A-Za-z0-9])")
TITLE_SINGLE_SYMBOL_RE = re.compile(r"(?<![A-Za-z0-9])(?P<code>[A-Za-z])(?![A-Za-z0-9])")
CONTEXT_WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{1,12}")

MARKET_CONTEXT_WORDS = (
    "上涨",
    "下跌",
    "涨",
    "跌",
    "反弹",
    "回落",
    "偏强",
    "偏弱",
    "震荡",
    "库存",
    "基差",
    "开工",
    "利润",
    "持仓",
    "成交",
    "供应",
    "需求",
    "供需",
    "价格",
    "现货",
    "期货",
    "合约",
    "主力",
)

STOP_ALIASES = {
    "收藏本页面",
    "打印",
    "日报",
    "月报",
    "周报",
    "宏观",
    "商品",
    "品种",
    "市场",
    "价格",
    "走势",
    "观点",
    "逻辑",
    "操作策略",
    "风险提示",
    "投资咨询",
    "研究所",
    "文档信息",
    "正文文本",
    "图片OCR文本",
}
GENERIC_CONTEXT_ALIASES = {
    "黑色",
    "有色",
    "能化",
    "贵金属",
    "农产品",
    "金融",
    "化工",
    "板块",
    "期货",
    "合约",
    "主力",
    "库存",
    "基差",
    "利润",
    "价格",
    "需求",
    "供应",
    "供需",
}
NEW_PRODUCT_STOP_ALIASES = {
    "现货",
    "盘面",
    "油脂",
    "粕类",
    "蛋白粕",
    "豆菜粕",
    "大豆",
    "西部",
}
NEW_PRODUCT_STOP_NORMALIZED = {normalize_alias(alias) for alias in NEW_PRODUCT_STOP_ALIASES}
INSTITUTION_ALIAS_STEMS = {
    "国信",
    "瑞达",
    "宝城",
    "五矿",
    "光大",
    "宏源",
    "冠通",
    "浙商",
    "中原",
    "恒泰",
    "倍特",
    "交子",
    "大越",
    "格林大华",
}
DISCLAIMER_NOISE_WORDS = (
    "扫码",
    "扫描",
    "关注",
    "下载",
    "订阅号",
    "服务号",
    "研究院",
    "研究所",
    "版权",
    "未经",
    "本报告",
    "本公司",
    "协会",
    "资格",
    "咨询证号",
    "投资咨询",
    "本人具有",
    "已具备",
    "须注明出处",
)
BAD_ASCII_ALIASES = {
    "HTTP",
    "WWW",
    "COM",
    "CN",
    "PDF",
    "HTML",
    "PMI",
    "PCE",
    "CFR",
    "FOB",
    "FAS",
    "OCR",
    "EMAIL",
    "TEL",
    "PHONE",
    "Mysteel",
}
FOREIGN_PREFIXES = ("COMEX", "LME", "WTI", "BRENT", "Brent", "美")
BRACKET_SPLIT_RE = re.compile(r"[/／、,，和及]")
SYMBOL_REPORT_RE = re.compile(r"^(?P<code>[A-Za-z]{1,5})(?:日报|周报|月报|季报)(?:\d{4,8})?$", re.IGNORECASE)
PURE_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[%‰])?$")
NUMBER_RANGE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?\s*(?:-|~|至|到)\s*[+-]?\d+(?:\.\d+)?(?:[%‰])?$")
COORDINATE_RE = re.compile(
    r"^[+-]?\d{1,3}(?:\.\d+)?\s*(?:°|度)?\s*[NSEW东西南北]?(?:\s*[,，/、]\s*[+-]?\d{1,3}(?:\.\d+)?\s*(?:°|度)?\s*[NSEW东西南北]?)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Occurrence:
    alias: str
    start: int
    end: int
    evidence_type: str
    product_key: str | None = None


class InstrumentDiscoverer:
    """Discover candidate aliases from raw documents."""

    def __init__(self, seeds: tuple[SeedInstrument, ...], config: BuildConfig | None = None) -> None:
        self.config = config or BuildConfig()
        self.seeds = seeds
        self.alias_index = build_alias_index(seeds)
        self.symbol_index = build_symbol_index(seeds)
        self.seed_by_key = {item.product_key: item for item in seeds}
        self._catalog_aliases = sorted(
            (
                alias
                for item in seeds
                for alias in item.seed_aliases
                if len(normalize_alias(alias)) >= 2
            ),
            key=len,
            reverse=True,
        )

    def discover(
        self,
        documents: tuple[Document, ...] | list[Document],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, CandidateEvidence]:
        candidates: dict[str, CandidateEvidence] = {}
        total = len(documents)
        for index, document in enumerate(documents, start=1):
            for occurrence in self._iter_occurrences(document):
                self._add_occurrence(candidates, document, occurrence)
            if progress_callback:
                progress_callback("scan", index, total, document.source_id)
        return candidates

    def _iter_occurrences(self, document: Document) -> list[_Occurrence]:
        title_text = "\n".join(part for part in (document.title, document.file_name) if part)
        body = _normalize_raw_text(document.raw_text)
        searchable = "\n".join(part for part in (title_text, body) if part)
        occurrences: list[_Occurrence] = []

        occurrences.extend(self._known_alias_occurrences(searchable))
        occurrences.extend(self._contract_occurrences(searchable))
        occurrences.extend(self._bracket_occurrences(searchable))
        occurrences.extend(self._label_occurrences(searchable))
        occurrences.extend(self._suffix_occurrences(searchable))
        occurrences.extend(self._symbol_occurrences(searchable, title_text))
        occurrences.extend(self._context_occurrences(searchable))
        return occurrences

    def _known_alias_occurrences(self, text: str) -> list[_Occurrence]:
        occurrences: list[_Occurrence] = []
        for alias in self._catalog_aliases:
            pattern = re.escape(alias)
            if re.fullmatch(r"[A-Za-z0-9]+", alias):
                pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                product_keys = self.alias_index.get(normalize_alias(alias), set())
                if self._is_negative_context(text, match.start(), next(iter(product_keys), None), alias):
                    occurrences.append(_Occurrence(alias, match.start(), match.end(), "negative_context", None))
                    continue
                occurrences.append(_Occurrence(match.group(0), match.start(), match.end(), "catalog_alias", _single(product_keys)))
        return occurrences

    def _contract_occurrences(self, text: str) -> list[_Occurrence]:
        occurrences: list[_Occurrence] = []
        for match in CONTRACT_RE.finditer(text):
            code = re.sub(r"\s+", "", match.group("code")).upper()
            product_key = self.symbol_index.get(code)
            if not product_key:
                continue
            occurrences.append(_Occurrence(code, match.start("code"), match.end("contract"), "contract_code", product_key))
        return occurrences

    def _bracket_occurrences(self, text: str) -> list[_Occurrence]:
        occurrences: list[_Occurrence] = []
        for match in BRACKET_RE.finditer(text):
            raw_alias = display_alias(match.group("alias"))
            if not raw_alias:
                continue
            report_symbol = SYMBOL_REPORT_RE.match(raw_alias)
            if report_symbol:
                code = report_symbol.group("code").upper()
                product_key = self.symbol_index.get(code)
                if product_key:
                    occurrences.append(_Occurrence(code, match.start("alias"), match.end("alias"), "title_symbol", product_key))
                    continue
            split_aliases = [display_alias(part) for part in BRACKET_SPLIT_RE.split(raw_alias)]
            if len(split_aliases) > 1:
                for part in split_aliases:
                    product_keys = self.alias_index.get(normalize_alias(part), set())
                    if product_keys:
                        occurrences.append(
                            _Occurrence(part, match.start("alias"), match.end("alias"), "bracket_heading", _single(product_keys))
                        )
                if occurrences and any(item.start == match.start("alias") for item in occurrences):
                    continue
            product_keys = self.alias_index.get(normalize_alias(raw_alias), set())
            occurrences.append(_Occurrence(raw_alias, match.start("alias"), match.end("alias"), "bracket_heading", _single(product_keys)))
        return occurrences

    def _label_occurrences(self, text: str) -> list[_Occurrence]:
        return [
            _Occurrence(
                display_alias(match.group("alias")),
                match.start("alias"),
                match.end("alias"),
                "label_field",
                _single(self.alias_index.get(normalize_alias(match.group("alias")), set())),
            )
            for match in LABEL_RE.finditer(text)
        ]

    def _suffix_occurrences(self, text: str) -> list[_Occurrence]:
        occurrences: list[_Occurrence] = []
        for match in CHINESE_SUFFIX_RE.finditer(text):
            raw_alias = display_alias(match.group("alias"))
            raw_alias = re.sub(r"^(?:当前|近期|短期|长期|国内|国际|外盘|主力|品种|商品)", "", raw_alias)
            if raw_alias:
                occurrences.append(
                    _Occurrence(
                        raw_alias,
                        match.start("alias"),
                        match.end("alias"),
                        "suffix_pattern",
                        _single(self.alias_index.get(normalize_alias(raw_alias)), None),
                    )
                )
        return occurrences

    def _symbol_occurrences(self, text: str, title_text: str) -> list[_Occurrence]:
        occurrences: list[_Occurrence] = []
        for match in BARE_SYMBOL_RE.finditer(text):
            code = match.group("code").upper()
            product_key = self.symbol_index.get(code)
            if product_key and self._has_market_context(text, match.start(), match.end()):
                occurrences.append(_Occurrence(match.group("code"), match.start(), match.end(), "symbol_context", product_key))

        for match in SPLIT_SYMBOL_RE.finditer(text):
            code = re.sub(r"\s+", "", match.group("code")).upper()
            product_key = self.symbol_index.get(code)
            if product_key and len(code) >= 2 and self._has_market_context(text, match.start(), match.end()):
                occurrences.append(_Occurrence(code, match.start(), match.end(), "ocr_split_symbol", product_key))

        for match in TITLE_SINGLE_SYMBOL_RE.finditer(title_text):
            code = match.group("code").upper()
            product_key = self.symbol_index.get(code)
            if product_key:
                occurrences.append(_Occurrence(code, match.start(), match.end(), "title_symbol", product_key))
        return occurrences

    def _context_occurrences(self, text: str) -> list[_Occurrence]:
        occurrences: list[_Occurrence] = []
        for match in CONTEXT_WORD_RE.finditer(text):
            raw_alias = display_alias(match.group(0))
            if len(raw_alias) < 2 or not self._has_market_context(text, match.start(), match.end()):
                continue
            normalized = normalize_alias(raw_alias)
            product_keys = self.alias_index.get(normalized)
            if product_keys:
                occurrences.append(_Occurrence(raw_alias, match.start(), match.end(), "market_context", _single(product_keys)))
        return occurrences

    def _add_occurrence(
        self,
        candidates: dict[str, CandidateEvidence],
        document: Document,
        occurrence: _Occurrence,
    ) -> None:
        raw_alias = display_alias(occurrence.alias)
        normalized = normalize_alias(raw_alias)
        if not normalized:
            return

        snippet = self._snippet(document.raw_text, occurrence.start, occurrence.end)
        evidence = candidates.get(normalized)
        if evidence is None:
            evidence = CandidateEvidence(raw_alias=raw_alias, normalized_alias=normalized)
            candidates[normalized] = evidence

        rejection_reason = self._alias_rejection_reason(raw_alias, occurrence.evidence_type)
        if rejection_reason:
            evidence.negative_reasons.add(rejection_reason)
            return
        if occurrence.product_key is None and normalized in NEW_PRODUCT_STOP_NORMALIZED:
            evidence.negative_reasons.add("generic_or_sector_term")
            return
        if occurrence.evidence_type == "negative_context":
            evidence.negative_reasons.add("foreign_market_context")
            return
        if occurrence.product_key and self._is_negative_context(document.raw_text, occurrence.start, occurrence.product_key, raw_alias):
            evidence.negative_reasons.add("foreign_market_context")
            return

        evidence.add_occurrence(
            source_id=document.source_id,
            snippet=snippet,
            evidence_type=occurrence.evidence_type,
            product_key=occurrence.product_key,
            config=self.config,
        )

    def _snippet(self, text: str, start: int, end: int) -> str:
        left = max(0, start - self.config.context_window)
        right = min(len(text), end + self.config.context_window)
        return text[left:right]

    def _has_market_context(self, text: str, start: int, end: int) -> bool:
        context = text[max(0, start - 28):min(len(text), end + 28)]
        return any(word in context for word in MARKET_CONTEXT_WORDS)

    def _is_negative_context(self, text: str, start: int, product_key: str | None, alias: str) -> bool:
        before = text[max(0, start - 12):start]
        after = text[start:start + 32]
        context = f"{before}{alias}{after}"
        if "@" in before or re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", context):
            return True
        for prefix in FOREIGN_PREFIXES:
            if before.casefold().endswith(prefix.casefold()):
                return True
        for prefix in NEGATIVE_CONTEXTS_BY_KEY.get(product_key or "", ()):
            if before.casefold().endswith(prefix.casefold()):
                return True
        return False

    def _alias_rejection_reason(self, alias: str, evidence_type: str) -> str | None:
        normalized_display = display_alias(alias)
        normalized = normalize_alias(alias)
        if not normalized:
            return "bad_alias_shape"
        if _contains_control_character(normalized_display):
            return "control_character"
        if _looks_like_mojibake(normalized_display):
            return "mojibake"
        if _is_numeric_coordinate_or_range(normalized_display):
            return "numeric_coordinate_or_range"
        if _is_punctuation_dominated(normalized_display):
            return "punctuation_dominated"
        if normalized_display in STOP_ALIASES or normalized_display in GENERIC_CONTEXT_ALIASES:
            return "bad_alias_shape"
        if normalized_display in INSTITUTION_ALIAS_STEMS or any(word in normalized_display for word in DISCLAIMER_NOISE_WORDS):
            return "institution_or_disclaimer"
        if normalized_display.startswith("图片分片"):
            return "bad_alias_shape"
        if re.search(r"\d+\s*/\s*\d+", normalized_display):
            return "numeric_coordinate_or_range"
        if SYMBOL_REPORT_RE.match(normalized_display):
            return "bad_alias_shape"
        if normalized_display.startswith("美") and normalize_alias(normalized_display) not in self.alias_index:
            return "bad_alias_shape"
        if normalized_display.upper() in BAD_ASCII_ALIASES:
            return "bad_alias_shape"
        if evidence_type in {"bracket_heading", "label_field", "suffix_pattern"} and len(normalized) > 16:
            return "bad_alias_shape"
        if re.fullmatch(r"\d+(?:/\d+)?", normalized_display):
            return "numeric_coordinate_or_range"
        if re.fullmatch(r"[FZ]\d{5,}", normalized_display, flags=re.IGNORECASE):
            return "bad_alias_shape"
        if re.search(r"\.(?:com|cn|pdf|html?)$", normalized_display, flags=re.IGNORECASE):
            return "bad_alias_shape"
        if re.search(r"qh\d+|www|http|@", normalized_display, flags=re.IGNORECASE):
            return "bad_alias_shape"
        return None


def _normalize_raw_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    # Repair common OCR spacing in all-uppercase product codes while preserving
    # original Chinese boundaries and line breaks for snippets.
    text = re.sub(r"(?<![A-Za-z])([A-Za-z])\s+([A-Za-z])(?=\s*[A-Za-z0-9])", r"\1\2", text)
    return text


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(char).startswith("C") and not char.isspace() for char in value)


def _looks_like_mojibake(value: str) -> bool:
    if "\ufffd" in value:
        return True
    return any("\u0080" <= char <= "\u00bf" for char in value)


def _is_numeric_coordinate_or_range(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    return bool(
        PURE_NUMBER_RE.fullmatch(compact)
        or NUMBER_RANGE_RE.fullmatch(compact)
        or COORDINATE_RE.fullmatch(compact)
    )


def _is_punctuation_dominated(value: str) -> bool:
    non_whitespace = [char for char in value if not char.isspace()]
    if not non_whitespace:
        return True
    punctuation = sum(
        unicodedata.category(char).startswith(("P", "S"))
        for char in non_whitespace
    )
    return punctuation / len(non_whitespace) >= 0.4


def _single(values: set[str] | None, default: str | None = None) -> str | None:
    if not values:
        return default
    if len(values) == 1:
        return next(iter(values))
    return default
