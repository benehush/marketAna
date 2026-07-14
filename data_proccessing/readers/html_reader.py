"""Small, dependency-local HTML正文 reader."""

from __future__ import annotations

from pathlib import Path
import re

from bs4 import BeautifulSoup

from data_proccessing.models import Document


def read_html(path: str | Path) -> Document:
    file_path = Path(path)
    html = file_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        node.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.body or soup
    text = _normalize(body.get_text("\n", strip=True))
    return Document(
        source_id=str(file_path),
        raw_text=text,
        title=title,
        file_name=file_path.name,
        file_type="html",
        metadata={"parser": "beautifulsoup"},
    )


def _normalize(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
