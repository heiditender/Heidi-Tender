from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List

from .constants import ALLOWED_EXTENSIONS, CONTEXT_FILE_MAX_BYTES, MAX_FILE_BYTES, SQL_CHUNK_BYTES
from .openai_client import upload_file


def collect_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".~lock."):
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        files.append(path)
    return files


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if not key:
                continue
            os.environ.setdefault(key, value)
    except Exception:
        return


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_final_result(prompt_result: dict) -> dict:
    return {
        "tender_products": prompt_result.get("tender_products", []),
        "match_results": prompt_result.get("match_results", []),
    }


def upload_tender_files(
    base_url: str,
    api_key: str,
    purpose: str,
    tender_files: List[Path],
) -> List[str]:
    tender_file_ids: List[str] = []
    for path in tender_files:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            print(f"Skipping {path.name}: {size} bytes exceeds 512MB", file=sys.stderr)
            continue
        if size > CONTEXT_FILE_MAX_BYTES and path.suffix.lower() != ".sql":
            print(
                f"Skipping {path.name}: {size} bytes exceeds 32MB context limit",
                file=sys.stderr,
            )
            continue
        if path.suffix.lower() == ".sql":
            print(f"Uploading {path.name} as text ({size} bytes)...")
            if size <= CONTEXT_FILE_MAX_BYTES:
                with path.open("rb") as src, tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                    shutil.copyfileobj(src, tmp)
                    tmp_path = Path(tmp.name)
                try:
                    file_id = upload_file(
                        base_url,
                        api_key,
                        tmp_path,
                        purpose,
                        upload_name=f"{path.name}.txt",
                    )
                    tender_file_ids.append(file_id)
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                with path.open("rb") as src:
                    part_idx = 0
                    buffer: list[bytes] = []
                    buffer_size = 0
                    for line in src:
                        buffer.append(line)
                        buffer_size += len(line)
                        if buffer_size >= SQL_CHUNK_BYTES:
                            part_idx += 1
                            with tempfile.NamedTemporaryFile(
                                suffix=f".part{part_idx:04d}.txt", delete=False
                            ) as tmp:
                                tmp.writelines(buffer)
                                tmp_path = Path(tmp.name)
                            buffer = []
                            buffer_size = 0
                            try:
                                file_id = upload_file(
                                    base_url,
                                    api_key,
                                    tmp_path,
                                    purpose,
                                    upload_name=f"{path.name}.part{part_idx:04d}.txt",
                                )
                                tender_file_ids.append(file_id)
                            finally:
                                try:
                                    tmp_path.unlink(missing_ok=True)
                                except Exception:
                                    pass
                    if buffer:
                        part_idx += 1
                        with tempfile.NamedTemporaryFile(
                            suffix=f".part{part_idx:04d}.txt", delete=False
                        ) as tmp:
                            tmp.writelines(buffer)
                            tmp_path = Path(tmp.name)
                        try:
                            file_id = upload_file(
                                base_url,
                                api_key,
                                tmp_path,
                                purpose,
                                upload_name=f"{path.name}.part{part_idx:04d}.txt",
                            )
                            tender_file_ids.append(file_id)
                        finally:
                            try:
                                tmp_path.unlink(missing_ok=True)
                            except Exception:
                                pass
            continue
        print(f"Uploading {path.name} ({size} bytes)...")
        file_id = upload_file(base_url, api_key, path, purpose)
        tender_file_ids.append(file_id)
    return tender_file_ids
