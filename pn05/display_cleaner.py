"""
Utilities for user-facing text cleanup.

The parser/cleaner may preserve useful market text that contains embedded PDF
headers, analyst credentials, or contact details. These helpers remove that
presentation noise before text is saved as a refined display field or returned
from API serializers.
"""

from __future__ import annotations

import re

__all__ = ["clean_display_text", "has_residual_display_noise"]


_CONTACT_AND_CREDENTIAL_PATTERNS: tuple[str, ...] = (
    r"(?:基本\s*)?(?:投资咨询|从业资格|执业资格|期货从业|证券从业)\s*证号\s*[:：]?\s*[A-Z]?\d{5,}",
    r"(?:E[-\s]?MAIL|Email|email|邮箱|电子邮箱)\s*[:：]?\s*[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    r"(?:联系电话|咨询电话|客服电话|客服热线|电话|传真|手机)\s*[:：]?\s*(?:\+?86[-\s]?)?(?:\d{3,4}[-\s]?\d{6,8}|\d{3}[-\s]?\d{3}[-\s]?\d{4}|\d{7,12})",
    r"(?:网址|网站)\s*[:：]?\s*(?:https?://)?(?:www\.)?[A-Za-z0-9.\-/]+",
    r"https?://\S+",
    r"\bwww\.[A-Za-z0-9.\-/]+",
)

_INLINE_NOISE_PATTERNS: tuple[str, ...] = (
    *_CONTACT_AND_CREDENTIAL_PATTERNS,
    r"请务必(?:仔细)?阅读正文后免责(?:申明|声明|条款)?",
    r"HTTP://WWW\.QH168\.COM\.CN\s*\d*\s*/\s*\d*",
    r"(?i)all rights reserved",
)

_NOISE_LINE_KEYWORDS: tuple[str, ...] = (
    "免责声明",
    "免责申明",
    "免责条款",
    "版权声明",
    "未经书面许可",
    "不得转载",
    "不构成投资建议",
    "不构成买卖建议",
    "本报告由",
    "研究所团队完成",
    "以上文中涉及数据来自",
    "地址：",
    "联系人：",
    "东海期货有限责任公司研究所",
)


def clean_display_text(text: str | None, *, max_chars: int | None = None) -> str:
    """Return compact, user-facing text with common report noise removed."""
    if not text:
        return ""

    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"```(?:\w+)?\s*([\s\S]*?)\s*```", r"\1", normalized)
    normalized = re.sub(r"(?m)^#{2,}\s*Page\s+\d+\s*$", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?m)^#+\s*文档信息\s*$", "", normalized)
    normalized = re.sub(r"(?m)^(来源文件|解析器)\s*[:：].*$", "", normalized)

    lines: list[str] = []
    for raw_line in normalized.splitlines():
        cleaned = _remove_inline_noise(raw_line)
        cleaned = _compact_inline_spaces(cleaned)
        cleaned = _strip_orphan_labels(cleaned)
        if not cleaned:
            continue
        if _is_noise_line(cleaned):
            continue
        lines.append(cleaned)

    compacted = "\n".join(_dedupe_adjacent(lines))
    compacted = re.sub(r"\n{2,}", "\n", compacted)
    compacted = re.sub(r"[ \t]{2,}", " ", compacted).strip()
    if max_chars is not None and max_chars > 0 and len(compacted) > max_chars:
        compacted = compacted[:max_chars].rstrip("，,；;、 ") + "。"
    return compacted


def has_residual_display_noise(text: str | None) -> bool:
    """Detect contact/credential/footer noise after model generation."""
    if not text:
        return False
    compact = re.sub(r"\s+", "", str(text))
    if any(keyword in compact for keyword in ("从业资格证号", "投资咨询证号", "免责申明", "免责声明")):
        return True
    return any(re.search(pattern, str(text), flags=re.IGNORECASE) for pattern in _CONTACT_AND_CREDENTIAL_PATTERNS)


def _remove_inline_noise(line: str) -> str:
    text = line.strip()
    for pattern in _INLINE_NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s*/\s*\d+\b", " ", text)
    return text


def _compact_inline_spaces(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([，。；：！？、])", r"\1", text)
    text = re.sub(r"([【（(])\s+", r"\1", text)
    text = re.sub(r"\s+([】）)])", r"\1", text)
    return text.strip(" \t:：,，;；")


def _strip_orphan_labels(text: str) -> str:
    return re.sub(r"^(?:基本|联系电话|咨询电话|客服电话|客服热线|电话|传真|邮箱)\s*[:：]?\s*$", "", text).strip()


def _is_noise_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if any(keyword in compact for keyword in _NOISE_LINE_KEYWORDS):
        return True
    if re.fullmatch(r"第?\d+页?", compact):
        return True
    if re.fullmatch(r"[\d/\-.]+", compact):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{2,16}(?:期货)?(?:有限责任)?公司(?:研究所)?", compact):
        return True
    return False


def _dedupe_adjacent(lines: list[str]) -> list[str]:
    result: list[str] = []
    previous = ""
    for line in lines:
        key = re.sub(r"\s+", "", line)
        if key and key != previous:
            result.append(line)
            previous = key
    return result
