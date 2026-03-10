#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List

import requests

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
PIM_STORE_ID_FILE = Path(__file__).resolve().parents[1] / ".pim_vector_store_id"


def _collect_files(root: Path) -> List[Path]:
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


def _load_env_file(path: Path) -> None:
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


def _load_pim_store_id() -> str | None:
    env_id = os.getenv("PIM_VECTOR_STORE_ID")
    if env_id:
        return env_id.strip()
    if PIM_STORE_ID_FILE.exists():
        value = PIM_STORE_ID_FILE.read_text(encoding="utf-8").strip()
        return value or None
    return None


def _save_pim_store_id(store_id: str) -> None:
    try:
        PIM_STORE_ID_FILE.write_text(store_id, encoding="utf-8")
    except Exception:
        return


def _upload_file(
    base_url: str,
    api_key: str,
    path: Path,
    purpose: str,
    upload_name: str | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/files"
    headers = {"Authorization": f"Bearer {api_key}"}
    with path.open("rb") as fh:
        files = {"file": (upload_name or path.name, fh)}
        data = {"purpose": purpose}
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=300)
    if resp.status_code >= 400:
        raise RuntimeError(f"upload failed for {path.name}: {resp.status_code} {resp.text}")
    payload = resp.json()
    file_id = payload.get("id")
    if not file_id:
        raise RuntimeError(f"upload failed for {path.name}: missing file id")
    return file_id


def _extract_output_json(response: dict) -> dict:
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return json.loads(content["text"])
    raise RuntimeError("No output_text JSON found in response")


def _build_final_result(prompt_result: dict) -> dict:
    return {
        "tender_products": prompt_result.get("tender_products", []),
        "match_results": prompt_result.get("match_results", []),
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _call_responses(base_url: str, api_key: str, model: str, system_prompt: str, file_ids: List[str]) -> dict:
    url = f"{base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    file_items = [{"type": "input_file", "file_id": file_id} for file_id in file_ids]
    user_text = (
        "You are given a tender pack. Read all files and return the JSON described by the system prompt."
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": system_prompt},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_text},
                    *file_items,
                ],
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=600)
    if resp.status_code >= 400:
        raise RuntimeError(f"responses call failed: {resp.status_code} {resp.text}")
    return resp.json()


def _create_vector_store(base_url: str, api_key: str, name: str) -> dict:
    url = f"{base_url.rstrip('/')}/vector_stores"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2",
    }
    resp = requests.post(url, headers=headers, json={"name": name}, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"vector store create failed: {resp.status_code} {resp.text}")
    return resp.json()


def _create_file_batch(base_url: str, api_key: str, vector_store_id: str, file_ids: List[str]) -> dict:
    url = f"{base_url.rstrip('/')}/vector_stores/{vector_store_id}/file_batches"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2",
    }
    resp = requests.post(url, headers=headers, json={"file_ids": file_ids}, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"file batch create failed: {resp.status_code} {resp.text}")
    return resp.json()


def _poll_file_batch(
    base_url: str,
    api_key: str,
    vector_store_id: str,
    batch_id: str,
    *,
    timeout_sec: int = 1800,
    interval_sec: int = 5,
) -> dict:
    url = f"{base_url.rstrip('/')}/vector_stores/{vector_store_id}/file_batches/{batch_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2",
    }
    waited = 0
    while True:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code >= 400:
            raise RuntimeError(f"file batch poll failed: {resp.status_code} {resp.text}")
        payload = resp.json()
        status = payload.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return payload
        if waited >= timeout_sec:
            raise RuntimeError(f"file batch poll timed out after {timeout_sec}s")
        time.sleep(interval_sec)
        waited += interval_sec


def _call_responses_file_search(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    vector_store_id: str,
    *,
    max_num_results: int = 12,
    user_text: str | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if not user_text:
        user_text = (
            "Use file_search as needed to read the files, then return the JSON described by the system prompt."
        )
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": system_prompt},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_text},
                ],
            },
        ],
        "tools": [
            {
                "type": "file_search",
                "vector_store_ids": [vector_store_id],
                "max_num_results": max_num_results,
            }
        ],
        "include": ["file_search_call.results"],
        "text": {"format": {"type": "json_object"}},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=600)
    if resp.status_code >= 400:
        raise RuntimeError(f"responses call failed: {resp.status_code} {resp.text}")
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload tender pack files and extract JSON via OpenAI API")
    parser.add_argument("pack_dir", help="Path to tender pack directory")
    parser.add_argument("--prompt", default="prompts/initial_prompt.txt", help="System prompt file")
    parser.add_argument("--output", default="output.json", help="Output JSON file")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"), help="Model name")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--purpose", default=os.getenv("OPENAI_FILE_PURPOSE", "user_data"))
    parser.add_argument("--mode", choices=["direct", "file_search"], default="file_search")
    parser.add_argument("--max-search-results", type=int, default=12)
    parser.add_argument("--reindex-pim", action="store_true")
    args = parser.parse_args()

    cwd_env = Path.cwd() / ".env"
    script_env = Path(__file__).resolve().parents[1] / ".env"
    _load_env_file(cwd_env)
    if script_env != cwd_env:
        _load_env_file(script_env)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2

    pack_dir = Path(args.pack_dir).resolve()
    if not pack_dir.exists():
        print(f"pack_dir not found: {pack_dir}", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt).resolve()
    if not prompt_path.exists():
        print(f"prompt file not found: {prompt_path}", file=sys.stderr)
        return 2

    system_prompt = prompt_path.read_text(encoding="utf-8")

    tender_files = _collect_files(pack_dir)
    if not tender_files:
        print("No supported files found in pack", file=sys.stderr)
        return 2

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
                    file_id = _upload_file(
                        args.base_url,
                        api_key,
                        tmp_path,
                        args.purpose,
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
                                file_id = _upload_file(
                                    args.base_url,
                                    api_key,
                                    tmp_path,
                                    args.purpose,
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
                            file_id = _upload_file(
                                args.base_url,
                                api_key,
                                tmp_path,
                                args.purpose,
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
        file_id = _upload_file(args.base_url, api_key, path, args.purpose)
        tender_file_ids.append(file_id)

    if not tender_file_ids:
        print("No tender files uploaded", file=sys.stderr)
        return 2

    if args.mode == "direct":
        print(f"Calling responses with {len(tender_file_ids)} files...")
        response = _call_responses(args.base_url, api_key, args.model, system_prompt, tender_file_ids)
    else:
        print(f"Creating tender vector store for {len(tender_file_ids)} files...")
        tender_vs = _create_vector_store(args.base_url, api_key, "tender_pack_vs")
        tender_vs_id = tender_vs.get("id")
        if not tender_vs_id:
            print("Tender vector store creation failed: missing id", file=sys.stderr)
            return 2
        print(f"Tender vector store id: {tender_vs_id}")
        tender_batch = _create_file_batch(args.base_url, api_key, tender_vs_id, tender_file_ids)
        tender_batch_id = tender_batch.get("id")
        if not tender_batch_id:
            print("Tender file batch creation failed: missing id", file=sys.stderr)
            return 2
        print(f"Indexing tender files (batch {tender_batch_id})...")
        tender_batch_result = _poll_file_batch(args.base_url, api_key, tender_vs_id, tender_batch_id)
        tender_status = tender_batch_result.get("status")
        if tender_status != "completed":
            print(f"Tender batch status: {tender_status}", file=sys.stderr)
            print(json.dumps(tender_batch_result, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2

        pim_vs_id = _load_pim_store_id()
        if not pim_vs_id or args.reindex_pim:
            pim_sql = Path("/home/daz/all_things_for_genai_hackathon/pim.sql")
            if not pim_sql.exists():
                print("pim.sql not found", file=sys.stderr)
                return 2
            pim_file_ids: List[str] = []
            size = pim_sql.stat().st_size
            if size > MAX_FILE_BYTES:
                print(f"Skipping pim.sql: {size} bytes exceeds 512MB", file=sys.stderr)
                return 2
            print(f"Uploading pim.sql as text ({size} bytes)...")
            if size <= CONTEXT_FILE_MAX_BYTES:
                with pim_sql.open("rb") as src, tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                    shutil.copyfileobj(src, tmp)
                    tmp_path = Path(tmp.name)
                try:
                    file_id = _upload_file(
                        args.base_url,
                        api_key,
                        tmp_path,
                        args.purpose,
                        upload_name=f"{pim_sql.name}.txt",
                    )
                    pim_file_ids.append(file_id)
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                with pim_sql.open("rb") as src:
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
                                file_id = _upload_file(
                                    args.base_url,
                                    api_key,
                                    tmp_path,
                                    args.purpose,
                                    upload_name=f"{pim_sql.name}.part{part_idx:04d}.txt",
                                )
                                pim_file_ids.append(file_id)
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
                            file_id = _upload_file(
                                args.base_url,
                                api_key,
                                tmp_path,
                                args.purpose,
                                upload_name=f"{pim_sql.name}.part{part_idx:04d}.txt",
                            )
                            pim_file_ids.append(file_id)
                        finally:
                            try:
                                tmp_path.unlink(missing_ok=True)
                            except Exception:
                                pass
            print("Creating PIM vector store...")
            pim_vs = _create_vector_store(args.base_url, api_key, "pim_sql_vs")
            pim_vs_id = pim_vs.get("id")
            if not pim_vs_id:
                print("PIM vector store creation failed: missing id", file=sys.stderr)
                return 2
            print(f"PIM vector store id: {pim_vs_id}")
            pim_batch = _create_file_batch(args.base_url, api_key, pim_vs_id, pim_file_ids)
            pim_batch_id = pim_batch.get("id")
            if not pim_batch_id:
                print("PIM file batch creation failed: missing id", file=sys.stderr)
                return 2
            print(f"Indexing PIM files (batch {pim_batch_id})...")
            pim_batch_result = _poll_file_batch(args.base_url, api_key, pim_vs_id, pim_batch_id)
            pim_status = pim_batch_result.get("status")
            if pim_status != "completed":
                print(f"PIM batch status: {pim_status}", file=sys.stderr)
                print(json.dumps(pim_batch_result, ensure_ascii=False, indent=2), file=sys.stderr)
                return 2
            _save_pim_store_id(pim_vs_id)
        else:
            print(f"Using existing PIM vector store: {pim_vs_id}")

        extract_prompt_path = Path("prompts/extract_requirements_prompt.txt")
        extract_prompt = extract_prompt_path.read_text(encoding="utf-8")
        print("Calling file_search to extract tender requirements...")
        requirements_response = _call_responses_file_search(
            args.base_url,
            api_key,
            args.model,
            extract_prompt,
            tender_vs_id,
            max_num_results=args.max_search_results,
            user_text="Extract tender product requirements as JSON.",
        )
        requirements_json = _extract_output_json(requirements_response)
        _write_json(Path("requirements.json"), requirements_json)

        print("Calling file_search to match against PIM...")
        match_response = _call_responses_file_search(
            args.base_url,
            api_key,
            args.model,
            system_prompt,
            pim_vs_id,
            max_num_results=args.max_search_results,
            user_text=f"Here are the extracted tender requirements JSON:\n{json.dumps(requirements_json, ensure_ascii=False)}",
        )
        response = match_response

    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        prompt_result = _extract_output_json(response)
        final_result = _build_final_result(prompt_result)
        _write_json(Path("prompt_result.json"), final_result)
    except Exception:
        pass
    print(f"Saved response to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
