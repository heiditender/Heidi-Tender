from __future__ import annotations

import logging
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader
from readability import Document

from apps.api.services.utils import compact_whitespace

logger = logging.getLogger(__name__)


def extract_pdf_text(path: str) -> tuple[str, int]:
    p = Path(path)
    if not p.exists():
        return "", 0
    try:
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n\n".join(x for x in pages if x)
        return compact_whitespace(text), len(reader.pages)
    except Exception as exc:
        logger.warning("PDF extract failed path=%s err=%s", path, exc)
        return "", 0


def extract_html_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    try:
        html = p.read_text(encoding="utf-8", errors="ignore")
        article = Document(html).summary()
        soup = BeautifulSoup(article, "html.parser")
        return compact_whitespace(soup.get_text(" "))
    except Exception as exc:
        logger.warning("HTML extract failed path=%s err=%s", path, exc)
        return ""
