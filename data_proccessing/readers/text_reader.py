"""TXT and already-parsed text reader."""

from __future__ import annotations

from pathlib import Path

from data_proccessing.models import Document


def read_text(path: str | Path) -> Document:
    file_path = Path(path)
    raw = file_path.read_bytes()
    text = _decode(raw)
    title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), "")
    return Document(
        source_id=str(file_path),
        raw_text=text,
        title=title,
        file_name=file_path.name,
        file_type="txt",
        metadata={"encoding": _encoding_name(raw, text)},
    )


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _encoding_name(raw: bytes, text: str) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "fallback"
