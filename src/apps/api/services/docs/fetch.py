from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.api.core.config import get_settings

logger = logging.getLogger(__name__)


class DocumentFetcher:
    def __init__(self):
        self.settings = get_settings()
        self.root = Path(self.settings.docs_storage_root)
        self.root.mkdir(parents=True, exist_ok=True)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def _download(self, url: str) -> tuple[bytes, str | None]:
        with httpx.Client(timeout=30) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.content, r.headers.get("content-type")

    def fetch_to_cache(self, notice_id: str, url: str) -> dict | None:
        if not url or not url.startswith(("http://", "https://")):
            return None

        try:
            content, mime_type = self._download(url)
        except Exception as exc:
            logger.warning("Doc download failed notice_id=%s url=%s err=%s", notice_id, url, exc)
            return None

        digest = hashlib.sha256(content).hexdigest()
        ext = ".pdf"
        if mime_type and "html" in mime_type:
            ext = ".html"
        elif mime_type and "json" in mime_type:
            ext = ".json"

        dest_dir = self.root / notice_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = dest_dir / f"{digest}{ext}"
        if not file_path.exists():
            file_path.write_bytes(content)

        return {
            "sha256": digest,
            "path": str(file_path),
            "mime_type": mime_type,
            "size": len(content),
        }
