from __future__ import annotations

from pathlib import Path

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".json",
    ".html",
    ".xml",
    ".doc",
    ".docx",
    ".rtf",
    ".odt",
    ".ppt",
    ".pptx",
    ".csv",
    ".xls",
    ".xlsx",
    ".sql",
}

MAX_FILE_BYTES = 512 * 1024 * 1024  # 512MB
CONTEXT_FILE_MAX_BYTES = 32 * 1024 * 1024  # 32MB per file for context stuffing
SQL_CHUNK_BYTES = 30 * 1024 * 1024

# /.../src/core/tender_pipeline/constants.py -> parents[2] == /.../src
BASE_DIR = Path(__file__).resolve().parents[2]
ARTICLE_SINGLE_RECORD_PATH = BASE_DIR / "core" / "articles_single_record.json"
ARTICLE_MULTI_RECORD_PATH = BASE_DIR / "core" / "articles_multi_records.json"

