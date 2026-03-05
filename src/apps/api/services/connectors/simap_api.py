from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.api.core.config import get_settings
from apps.api.services.utils import as_list, parse_datetime, safe_get

logger = logging.getLogger(__name__)


class SimpleRateLimiter:
    def __init__(self, requests_per_second: float = 1.0):
        self.min_interval = 1.0 / max(requests_per_second, 0.01)
        self._last_call_ts = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call_ts = time.monotonic()


class SimapApiConnector:
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.simap_base_url.rstrip("/")
        self.timeout = self.settings.simap_timeout_seconds
        self.limiter = SimpleRateLimiter(self.settings.simap_rps)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.settings.simap_token:
            headers["Authorization"] = f"Bearer {self.settings.simap_token}"
        return headers

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        self.limiter.wait()
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout, headers=self._headers()) as client:
            response = client.request(method, url, params=params)
            response.raise_for_status()
            return response.json()

    def list_publications(self, updated_since: str | None = None, limit: int = 50, language: str = "en") -> list[dict[str, Any]]:
        # Keep params permissive to tolerate SIMAP API version differences.
        params = {
            "limit": limit,
            "size": limit,
            "lang": language,
            "language": language,
        }
        if updated_since:
            params["updated_since"] = updated_since
            params["updatedSince"] = updated_since

        try:
            payload = self._request("GET", self.settings.simap_publications_path, params=params)
        except Exception as exc:
            logger.warning("SIMAP list_publications failed: %s", exc)
            return []

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "results", "data", "publications"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    def get_publication(
        self,
        publication_id: str,
        project_id: str | None = None,
        language: str = "en",
    ) -> dict[str, Any] | None:
        path = self.settings.simap_publication_detail_path
        replacements = {
            "projectId": project_id,
            "project_id": project_id,
            "publicationId": publication_id,
            "publication_id": publication_id,
        }
        for key, value in replacements.items():
            if value is not None:
                path = path.replace("{" + key + "}", str(value))

        if "{" in path and "}" in path:
            logger.warning(
                "SIMAP detail path has unresolved placeholders path=%s project_id=%s publication_id=%s",
                path,
                project_id,
                publication_id,
            )
            return None

        params = {"lang": language, "language": language}
        try:
            payload = self._request("GET", path, params=params)
            if isinstance(payload, dict):
                return payload
            return None
        except Exception as exc:
            logger.warning(
                "SIMAP get_publication failed project_id=%s publication_id=%s err=%s",
                project_id,
                publication_id,
                exc,
            )
            return None

    @staticmethod
    def normalize_publication(raw: dict[str, Any]) -> dict[str, Any]:
        publication_id = str(
            safe_get(raw, "id")
            or safe_get(raw, "publicationId")
            or safe_get(raw, "publication_id")
            or safe_get(raw, "noticeId")
            or safe_get(raw, "uuid")
            or ""
        ).strip()
        project_id = str(
            safe_get(raw, "projectId")
            or safe_get(raw, "project_id")
            or safe_get(raw, "project.id")
            or safe_get(raw, "project.projectId")
            or safe_get(raw, "project.idProject")
            or ""
        ).strip()

        buyer = safe_get(raw, "buyer") or safe_get(raw, "contractingAuthority") or {}
        if not isinstance(buyer, dict):
            buyer = {}

        docs = as_list(safe_get(raw, "documents") or safe_get(raw, "attachments") or [])
        normalized_docs = []
        for doc in docs:
            if isinstance(doc, dict):
                doc_url = safe_get(doc, "url") or safe_get(doc, "href")
                if not doc_url:
                    continue
                normalized_docs.append(
                    {
                        "url": doc_url,
                        "filename": safe_get(doc, "filename") or safe_get(doc, "name"),
                        "mime_type": safe_get(doc, "mime_type") or safe_get(doc, "mimeType") or safe_get(doc, "type"),
                        "raw": doc,
                    }
                )
            elif isinstance(doc, str) and doc.startswith("http"):
                normalized_docs.append({"url": doc, "filename": None, "mime_type": None, "raw": {"url": doc}})

        cpv_raw = as_list(safe_get(raw, "cpvCodes") or safe_get(raw, "cpv") or safe_get(raw, "cpv_codes"))
        cpv_codes = []
        for cpv in cpv_raw:
            if isinstance(cpv, dict):
                code = cpv.get("code") or cpv.get("value")
                if code:
                    cpv_codes.append(str(code))
            else:
                cpv_codes.append(str(cpv))

        langs = as_list(safe_get(raw, "languages") or safe_get(raw, "language"))

        return {
            "source": "simap",
            "source_id": publication_id,
            "publication_id": publication_id or None,
            "project_id": project_id or None,
            "title": safe_get(raw, "title") or safe_get(raw, "name") or safe_get(raw, "subject"),
            "description": safe_get(raw, "description") or safe_get(raw, "summary") or safe_get(raw, "body"),
            "buyer_name": safe_get(buyer, "name") or safe_get(raw, "buyerName") or safe_get(raw, "contractingAuthorityName"),
            "buyer_location": safe_get(buyer, "location") or safe_get(raw, "buyerLocation"),
            "cpv_codes": cpv_codes,
            "procedure_type": safe_get(raw, "procedureType") or safe_get(raw, "procedure") or safe_get(raw, "type"),
            "publication_date": parse_datetime(
                safe_get(raw, "publicationDate")
                or safe_get(raw, "publishedAt")
                or safe_get(raw, "datePublication")
                or safe_get(raw, "createdAt")
            ),
            "deadline_date": parse_datetime(
                safe_get(raw, "deadlineDate")
                or safe_get(raw, "submissionDeadline")
                or safe_get(raw, "deadline")
            ),
            "languages": [str(x) for x in langs if x],
            "region": safe_get(raw, "region") or safe_get(raw, "canton") or safe_get(raw, "buyer.canton"),
            "url": safe_get(raw, "url") or safe_get(raw, "publicationUrl") or safe_get(raw, "link"),
            "documents": normalized_docs,
            "raw_json": raw,
        }
