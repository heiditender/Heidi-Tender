from __future__ import annotations

import os
from pathlib import Path

from kb.kb_builder import DEFAULT_BASE, run_one_shot_pipeline
from kb.preprocess import DEFAULT_SRC
from kb.vector_store_sync import (
    DEFAULT_CORPUS_DIR,
    DEFAULT_MANIFEST,
    DEFAULT_STORE_NAME,
    find_existing_vector_store,
    sync_vector_store,
)


def _dir_has_files(path: Path) -> bool:
    return path.exists() and path.is_dir() and any(path.iterdir())


def has_local_kb_artifacts(base_dir: Path) -> bool:
    manifest_path = base_dir / DEFAULT_MANIFEST
    corpus_dir = base_dir / DEFAULT_CORPUS_DIR
    return manifest_path.exists() and _dir_has_files(corpus_dir)


def _store_brief(store: dict) -> dict:
    return {
        "id": store.get("id"),
        "name": store.get("name"),
        "status": store.get("status"),
        "created_at": store.get("created_at"),
        "file_counts": store.get("file_counts"),
        "metadata": store.get("metadata"),
    }


def ensure_kb_vector_store(
    *,
    src_dir: Path = Path(DEFAULT_SRC),
    base_dir: Path = Path(DEFAULT_BASE),
    vector_store_name: str = DEFAULT_STORE_NAME,
    kb_key: str = "lighting_kb",
    description: str | None = "Preprocessed lighting knowledge base for tender matching.",
    low_text_threshold: int = 20,
    force_rebuild_local: bool = False,
    batch_size: int = 100,
    file_purpose: str | None = None,
    max_files: int | None = None,
    poll_interval_sec: int = 5,
    wait_timeout_sec: int = 3600,
) -> dict:
    src_dir = src_dir.resolve()
    base_dir = base_dir.resolve()
    resolved_purpose = file_purpose or os.getenv("OPENAI_FILE_PURPOSE", "user_data")

    existing = find_existing_vector_store(
        vector_store_name=vector_store_name,
        kb_key=kb_key,
        base_dir=base_dir,
    )
    if existing is not None:
        return {
            "status": "already_exists",
            "message": "Found existing KB vector store under current API key.",
            "vector_store": _store_brief(existing),
            "kb_build": {"skipped": True, "reason": "vector_store_exists"},
            "vector_store_sync": {"skipped": True, "reason": "vector_store_exists"},
        }

    if has_local_kb_artifacts(base_dir) and not force_rebuild_local:
        kb_build_summary: dict = {
            "status": "reused_existing_local_kb_artifacts",
            "base_dir": str(base_dir),
            "manifest_path": str((base_dir / DEFAULT_MANIFEST).resolve()),
            "corpus_dir": str((base_dir / DEFAULT_CORPUS_DIR).resolve()),
        }
    else:
        kb_build_summary = run_one_shot_pipeline(
            src=src_dir,
            base_dir=base_dir,
            force=True,
            low_text_threshold=low_text_threshold,
        )

    sync_summary = sync_vector_store(
        base_dir=base_dir,
        manifest_path=(base_dir / DEFAULT_MANIFEST).resolve(),
        corpus_dir=(base_dir / DEFAULT_CORPUS_DIR).resolve(),
        vector_store_name=vector_store_name,
        kb_key=kb_key,
        description=description,
        batch_size=max(1, batch_size),
        file_purpose=resolved_purpose,
        dry_run=False,
        max_files=max_files,
        poll_interval_sec=max(1, poll_interval_sec),
        wait_timeout_sec=max(60, wait_timeout_sec),
    )

    return {
        "status": sync_summary.get("status") or "uploaded",
        "message": "Created or reused KB vector store and finished sync.",
        "vector_store": {
            "id": sync_summary.get("vector_store_id"),
            "name": sync_summary.get("vector_store_name"),
            "status": sync_summary.get("status"),
        },
        "kb_build": kb_build_summary,
        "vector_store_sync": sync_summary,
    }
