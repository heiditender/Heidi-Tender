#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from .common import iso_now, load_jsonl, sha256_file, write_json
from .kb_builder import DEFAULT_BASE

DEFAULT_MANIFEST = "reports_kb/manifest_upload_kb.jsonl"
DEFAULT_CORPUS_DIR = "upload_corpus_kb"
DEFAULT_STORE_NAME = "lighting_kb"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and value:
                os.environ.setdefault(key, value)
    except Exception:
        return


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _json_headers(api_key: str) -> dict[str, str]:
    headers = _auth_headers(api_key)
    headers["Content-Type"] = "application/json"
    return headers


def _resolve_api_credentials(base_dir: Path | None = None) -> tuple[str, str]:
    _load_env_file(Path.cwd() / ".env")
    _load_env_file(Path(__file__).resolve().parents[2] / ".env")
    if base_dir is not None:
        _load_env_file(base_dir / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (checked env + .env files)")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return api_key, base_url


def _request_with_retries(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: int = 120,
    max_retries: int = 3,
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
    **kwargs: Any,
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2**attempt)
            continue
        if resp.status_code in retry_statuses and attempt + 1 < max_retries:
            time.sleep(2**attempt)
            continue
        return resp
    if last_exc is not None:
        raise RuntimeError(f"Request failed after retries: {method} {url}: {last_exc}") from last_exc
    raise RuntimeError(f"Request failed after retries: {method} {url}")


def _list_vector_stores(base_url: str, api_key: str) -> list[dict]:
    url = f"{base_url}/vector_stores"
    stores: list[dict] = []
    after: str | None = None
    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after
        resp = _request_with_retries(
            "GET",
            url,
            headers=_auth_headers(api_key),
            params=params,
            timeout=60,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Failed to list vector stores: {resp.status_code} {resp.text[:500]}")
        payload = resp.json()
        data = payload.get("data") or []
        stores.extend(data)
        if payload.get("has_more") and data:
            after = data[-1].get("id")
            if not after:
                break
        else:
            break
    return stores


def _create_vector_store(
    base_url: str,
    api_key: str,
    *,
    name: str,
    metadata: dict[str, str],
    description: str | None = None,
) -> dict:
    url = f"{base_url}/vector_stores"
    payload: dict[str, Any] = {"name": name, "metadata": metadata}
    if description:
        payload["description"] = description
    resp = _request_with_retries(
        "POST",
        url,
        headers=_json_headers(api_key),
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to create vector store: {resp.status_code} {resp.text[:500]}")
    return resp.json()


def _upload_file(base_url: str, api_key: str, file_path: Path, purpose: str) -> str:
    url = f"{base_url}/files"
    last_error = ""
    for attempt in range(3):
        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh)}
            data = {"purpose": purpose}
            resp = _request_with_retries(
                "POST",
                url,
                headers=_auth_headers(api_key),
                files=files,
                data=data,
                timeout=300,
            )
        if resp.status_code >= 400:
            last_error = f"{resp.status_code} {resp.text[:500]}"
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Failed to upload file {file_path}: {last_error}")
        payload = resp.json()
        file_id = payload.get("id")
        if not file_id:
            raise RuntimeError(f"Upload returned no file id for {file_path}")
        return file_id
    raise RuntimeError(f"Failed to upload file {file_path}: {last_error}")


def _create_file_batch(
    base_url: str,
    api_key: str,
    vector_store_id: str,
    files_payload: list[dict[str, Any]],
) -> dict:
    url = f"{base_url}/vector_stores/{vector_store_id}/file_batches"
    payload = {"files": files_payload}
    resp = _request_with_retries(
        "POST",
        url,
        headers=_json_headers(api_key),
        json=payload,
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to create file batch: {resp.status_code} {resp.text[:500]}")
    return resp.json()


def _get_file_batch(base_url: str, api_key: str, vector_store_id: str, batch_id: str) -> dict:
    url = f"{base_url}/vector_stores/{vector_store_id}/file_batches/{batch_id}"
    resp = _request_with_retries(
        "GET",
        url,
        headers=_auth_headers(api_key),
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to get file batch {batch_id}: {resp.status_code} {resp.text[:500]}")
    return resp.json()


def _wait_batch(
    base_url: str,
    api_key: str,
    vector_store_id: str,
    batch_id: str,
    *,
    poll_interval_sec: int = 5,
    timeout_sec: int = 3600,
) -> dict:
    start = time.time()
    while True:
        payload = _get_file_batch(base_url, api_key, vector_store_id, batch_id)
        status = str(payload.get("status") or "")
        if status in {"completed", "failed", "cancelled"}:
            return payload
        if time.time() - start > timeout_sec:
            raise TimeoutError(f"Timed out waiting for batch {batch_id}")
        time.sleep(poll_interval_sec)


def _attributes_from_manifest_row(row: dict) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    attrs: dict[str, Any] = {}
    for key in ("source", "doc_kind", "topic", "lang_hint", "year_hint"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if value is None or value == "":
            continue
        attrs[key] = value
    ext = row.get("ext")
    if isinstance(ext, str) and ext:
        attrs["ext"] = ext
    section = row.get("section")
    if isinstance(section, str) and section:
        attrs["section"] = section
    return attrs


def _safe_store_file_total(store: dict) -> int:
    file_counts = store.get("file_counts")
    if not isinstance(file_counts, dict):
        return 0
    total = file_counts.get("total")
    return int(total) if isinstance(total, int) else 0


def find_existing_vector_store(
    *,
    vector_store_name: str,
    kb_key: str,
    base_dir: Path | None = None,
) -> dict | None:
    api_key, base_url = _resolve_api_credentials(base_dir)
    stores = _list_vector_stores(base_url, api_key)

    if not kb_key:
        return None

    candidates: list[tuple[int, int, dict]] = []
    for store in stores:
        status = str(store.get("status") or "")
        if status == "expired":
            continue
        metadata = store.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        key_match = metadata.get("kb_key") == kb_key
        if not key_match:
            continue

        name_match = bool(vector_store_name and str(store.get("name") or "") == vector_store_name)
        created_at = store.get("created_at")
        created_at_ts = int(created_at) if isinstance(created_at, int) else 0
        # Strictly match by kb_key. Prefer name-consistent store when tie-breaking.
        priority = 2 if name_match else 1
        candidates.append((priority, created_at_ts, store))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _find_existing_store(
    stores: list[dict],
    *,
    store_name: str,
    kb_key: str,
    kb_fingerprint: str,
    expected_file_count: int,
) -> dict | None:
    # Strong match: same kb_key + same fingerprint.
    for store in stores:
        metadata = store.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("kb_key") != kb_key:
            continue
        if metadata.get("kb_fingerprint") == kb_fingerprint:
            status = str(store.get("status") or "")
            if status != "expired":
                return store

    # Fallback: same kb_key + same total file count + active status.
    # Avoid matching by name only to prevent false positives across different KBs.
    for store in stores:
        metadata = store.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("kb_key") != kb_key:
            continue
        if store_name and str(store.get("name") or "") != store_name:
            continue
        status = str(store.get("status") or "")
        if status == "expired":
            continue
        if _safe_store_file_total(store) == expected_file_count and expected_file_count > 0:
            return store
    return None


def sync_vector_store(
    *,
    base_dir: Path,
    manifest_path: Path,
    corpus_dir: Path,
    vector_store_name: str,
    kb_key: str,
    description: str | None,
    batch_size: int,
    file_purpose: str,
    dry_run: bool,
    max_files: int | None,
    poll_interval_sec: int,
    wait_timeout_sec: int,
) -> dict:
    api_key, base_url = _resolve_api_credentials(base_dir)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus dir not found: {corpus_dir}")

    rows = load_jsonl(manifest_path)
    if max_files is not None:
        rows = rows[: max(0, max_files)]
    manifest_rows = len(rows)
    kb_fingerprint = sha256_file(manifest_path)

    stores = _list_vector_stores(base_url, api_key)
    existing = _find_existing_store(
        stores,
        store_name=vector_store_name,
        kb_key=kb_key,
        kb_fingerprint=kb_fingerprint,
        expected_file_count=manifest_rows,
    )
    if existing is not None:
        summary = {
            "status": "already_exists",
            "vector_store_id": existing.get("id"),
            "vector_store_name": existing.get("name"),
            "kb_key": kb_key,
            "kb_fingerprint": kb_fingerprint,
            "manifest_rows": manifest_rows,
            "created_at": existing.get("created_at"),
            "file_counts": existing.get("file_counts"),
            "message": "Matching vector store already exists. Skip upload.",
        }
        return summary

    if dry_run:
        return {
            "status": "dry_run_would_upload",
            "vector_store_name": vector_store_name,
            "kb_key": kb_key,
            "kb_fingerprint": kb_fingerprint,
            "manifest_rows": manifest_rows,
        }

    metadata = {
        "kb_key": kb_key,
        "kb_fingerprint": kb_fingerprint,
        "manifest_rows": str(manifest_rows),
        "pipeline": "upload_corpus_kb",
    }
    store = _create_vector_store(
        base_url,
        api_key,
        name=vector_store_name,
        metadata=metadata,
        description=description,
    )
    vector_store_id = store.get("id")
    if not isinstance(vector_store_id, str) or not vector_store_id:
        raise RuntimeError("Failed to create vector store: missing id")

    # Upload files.
    uploaded: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        rel = str(row.get("path") or "")
        if rel.startswith("upload_corpus_kb/"):
            rel = rel[len("upload_corpus_kb/") :]
        elif rel.startswith("upload_corpus/"):
            rel = rel[len("upload_corpus/") :]
        file_path = corpus_dir / rel
        if not file_path.exists():
            raise FileNotFoundError(f"File from manifest is missing: {file_path}")
        file_id = _upload_file(base_url, api_key, file_path, file_purpose)
        uploaded.append(
            {
                "file_id": file_id,
                "attributes": _attributes_from_manifest_row(row),
                "path": str(file_path),
                "index": idx,
            }
        )

    # Batch attach files to vector store and wait each batch.
    batches: list[dict[str, Any]] = []
    for i in range(0, len(uploaded), batch_size):
        chunk = uploaded[i : i + batch_size]
        files_payload = [{"file_id": item["file_id"], "attributes": item["attributes"]} for item in chunk]
        batch = _create_file_batch(base_url, api_key, vector_store_id, files_payload)
        batch_id = batch.get("id")
        if not isinstance(batch_id, str) or not batch_id:
            raise RuntimeError("Created batch without batch id")
        final_batch = _wait_batch(
            base_url,
            api_key,
            vector_store_id,
            batch_id,
            poll_interval_sec=poll_interval_sec,
            timeout_sec=wait_timeout_sec,
        )
        batches.append(final_batch)

    # Refresh store info.
    refreshed = None
    for store_obj in _list_vector_stores(base_url, api_key):
        if store_obj.get("id") == vector_store_id:
            refreshed = store_obj
            break

    failed_batches = [
        batch
        for batch in batches
        if str(batch.get("status") or "") in {"failed", "cancelled"}
    ]
    status = "uploaded_with_failures" if failed_batches else "uploaded"

    return {
        "status": status,
        "vector_store_id": vector_store_id,
        "vector_store_name": vector_store_name,
        "kb_key": kb_key,
        "kb_fingerprint": kb_fingerprint,
        "manifest_rows": manifest_rows,
        "uploaded_files": len(uploaded),
        "batch_count": len(batches),
        "failed_batch_count": len(failed_batches),
        "vector_store": refreshed or store,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One-click KB vector store sync: if matching KB exists under this API key, return it; "
            "otherwise create and upload."
        )
    )
    parser.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE),
        help="Base directory containing upload_corpus_kb and reports_kb/manifest_upload_kb.jsonl",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST,
        help="Manifest path (absolute or relative to --base-dir)",
    )
    parser.add_argument(
        "--corpus-dir",
        default=DEFAULT_CORPUS_DIR,
        help="Corpus directory path (absolute or relative to --base-dir)",
    )
    parser.add_argument(
        "--vector-store-name",
        default=DEFAULT_STORE_NAME,
        help="Target vector store name",
    )
    parser.add_argument(
        "--kb-key",
        default="lighting_kb",
        help="Logical KB key stored in vector store metadata for idempotent lookup",
    )
    parser.add_argument(
        "--description",
        default="Preprocessed lighting knowledge base for tender matching.",
        help="Vector store description",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="File batch size for vector store file batch API",
    )
    parser.add_argument(
        "--file-purpose",
        default=os.getenv("OPENAI_FILE_PURPOSE", "user_data"),
        help="Files API purpose value",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional upload cap for testing",
    )
    parser.add_argument(
        "--poll-interval-sec",
        type=int,
        default=5,
        help="Polling interval for file batch status",
    )
    parser.add_argument(
        "--wait-timeout-sec",
        type=int,
        default=3600,
        help="Timeout per file batch wait",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not create/upload, only check whether a matching store exists",
    )
    parser.add_argument(
        "--summary-out",
        default="reports_kb/vector_store_sync_summary.json",
        help="Summary output path (absolute or relative to --base-dir)",
    )
    return parser


def _resolve_relative(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = (base_dir / path).resolve()
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir).resolve()
    manifest_path = _resolve_relative(base_dir, args.manifest)
    corpus_dir = _resolve_relative(base_dir, args.corpus_dir)
    summary_out = Path(args.summary_out)
    if not summary_out.is_absolute():
        summary_out = (base_dir / summary_out).resolve()

    summary = sync_vector_store(
        base_dir=base_dir,
        manifest_path=manifest_path,
        corpus_dir=corpus_dir,
        vector_store_name=args.vector_store_name,
        kb_key=args.kb_key,
        description=args.description,
        batch_size=max(1, args.batch_size),
        file_purpose=args.file_purpose,
        dry_run=args.dry_run,
        max_files=args.max_files,
        poll_interval_sec=max(1, args.poll_interval_sec),
        wait_timeout_sec=max(60, args.wait_timeout_sec),
    )
    summary["generated_at"] = iso_now()
    summary["base_dir"] = str(base_dir)
    summary["manifest_path"] = str(manifest_path)
    summary["corpus_dir"] = str(corpus_dir)
    write_json(summary_out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
