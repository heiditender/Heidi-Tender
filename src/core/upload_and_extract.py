#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
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
BASE_DIR = Path(__file__).resolve().parents[1]


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


def _upload_file(
    base_url: str,
    api_key: str,
    path: Path,
    purpose: str,
    upload_name: str | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/files"
    headers = {"Authorization": f"Bearer {api_key}"}
    last_error = None
    for attempt in range(3):
        with path.open("rb") as fh:
            files = {"file": (upload_name or path.name, fh)}
            data = {"purpose": purpose}
            try:
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=300)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2 ** attempt)
                continue
        if resp.status_code in {429, 500, 502, 503, 504}:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"upload failed for {path.name}: {resp.status_code} {resp.text}")
        payload = resp.json()
        file_id = payload.get("id")
        if not file_id:
            raise RuntimeError(f"upload failed for {path.name}: missing file id")
        return file_id
    if last_error:
        raise RuntimeError(f"upload failed for {path.name}: {last_error}")
    raise RuntimeError(f"upload failed for {path.name}: service unavailable")


def _extract_output_json(response: dict) -> dict:
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    text = content["text"]
                    try:
                        return json.loads(text)
                    except Exception:
                        start = text.find("{")
                        end = text.rfind("}")
                        if start != -1 and end != -1 and end > start:
                            snippet = text[start : end + 1]
                            return json.loads(snippet)
    raise RuntimeError("No output_text JSON found in response")


def _extract_output_text(response: dict) -> str:
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
    raise RuntimeError("No output_text found in response")


def _build_final_result(prompt_result: dict) -> dict:
    return {
        "tender_products": prompt_result.get("tender_products", []),
        "match_results": prompt_result.get("match_results", []),
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _configure_dspy(model: str, api_key: str):
    try:
        import dspy  # type: ignore
    except Exception as exc:
        raise RuntimeError("dspy-ai is not installed. Install it with: pip install dspy-ai") from exc
    if api_key:
        os.environ.setdefault("OPENAI_API_KEY", api_key)
    lm = dspy.LM(model=model, model_type="responses")
    dspy.settings.configure(lm=lm)
    return dspy


def _run_dspy_generate_sql(
    model: str,
    api_key: str,
    requirements_json: dict,
    schema_json: dict,
    web_context: str = "",
) -> dict:
    _configure_dspy(model, api_key)
    from dspy_program import GenerateSQLModule

    program = GenerateSQLModule()
    prediction = program(
        requirements_json=json.dumps(requirements_json, ensure_ascii=False),
        schema_json=json.dumps(schema_json, ensure_ascii=False),
        web_context=web_context,
    )
    return json.loads(prediction.sql_queries_json)


def _run_dspy_extract_requirements(
    model: str,
    api_key: str,
    tender_text: str,
    web_context: str = "",
) -> dict:
    _configure_dspy(model, api_key)
    from dspy_program import ExtractRequirementsModule

    program = ExtractRequirementsModule()
    prediction = program(tender_text=tender_text, web_context=web_context)
    return json.loads(prediction.requirements_json)


def _run_dspy_format_match(
    model: str,
    api_key: str,
    requirements_json: dict,
    schema_json: dict,
    sql_results: list[dict],
    web_context: str = "",
) -> dict:
    _configure_dspy(model, api_key)
    from dspy_program import FormatMatchModule

    program = FormatMatchModule()
    prediction = program(
        requirements_json=json.dumps(requirements_json, ensure_ascii=False),
        schema_json=json.dumps(schema_json, ensure_ascii=False),
        sql_results_json=json.dumps(sql_results, ensure_ascii=False),
        web_context=web_context,
    )
    return json.loads(prediction.prompt_result_json)


def _call_responses(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    file_ids: List[str],
    *,
    user_text: str | None = None,
    tools: List[dict] | None = None,
    include: List[str] | None = None,
    json_mode: bool = True,
) -> dict:
    url = f"{base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    file_items = [{"type": "input_file", "file_id": file_id} for file_id in file_ids]
    if not user_text:
        user_text = (
            "You are given a tender pack. Read all files and return the JSON described by the system prompt."
        )
    payload: dict = {
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
    }
    if tools:
        payload["tools"] = tools
    if include:
        payload["include"] = include
    if json_mode and (not tools or not any(tool.get("type") == "web_search" for tool in tools)):
        payload["text"] = {"format": {"type": "json_object"}}
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=600)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in {429, 500, 502, 503, 504}:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"responses call failed: {resp.status_code} {resp.text}")
        return resp.json()
    if last_error:
        raise RuntimeError(f"responses call failed: {last_error}")
    raise RuntimeError("responses call failed: service unavailable")


def _call_web_search(
    base_url: str,
    api_key: str,
    model: str,
    query: str,
) -> dict:
    url = f"{base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": model,
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": query}]},
        ],
        "tools": [{"type": "web_search", "external_web_access": True}],
        "include": ["web_search_call.results"],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"web_search failed: {resp.status_code} {resp.text}")
    return resp.json()


def _collect_web_search_text(response: dict) -> List[str]:
    texts: List[str] = []
    for item in response.get("output", []):
        if item.get("type") != "web_search_call":
            continue
        for result in item.get("results") or []:
            title = result.get("title")
            snippet = result.get("snippet") or result.get("text")
            url = result.get("url")
            parts = [p for p in [title, snippet, url] if p]
            if parts:
                texts.append("\n".join(parts))
    return texts


def _write_debug_text(debug_dir: Path, name: str, text: str) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(text, encoding="utf-8")


def _write_debug_json(debug_dir: Path, name: str, payload: dict) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_mysql_query(container: str, user: str, password: str, database: str, sql: str) -> str:
    cmd = [
        "docker",
        "exec",
        container,
        "mysql",
        f"-u{user}",
        f"-p{password}",
        "-D",
        database,
        "--batch",
        "--raw",
        "-e",
        sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"MySQL query failed: {result.stderr.strip()}")
    return result.stdout


def _parse_mysql_tsv(output: str) -> List[dict]:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    headers = [header.strip().lower() for header in lines[0].split("\t")]
    rows: List[dict] = []
    for line in lines[1:]:
        values = line.split("\t")
        row = dict(zip(headers, values))
        rows.append(row)
    return rows


def _fetch_schema_metadata(
    container: str,
    user: str,
    password: str,
    database: str,
    tables: List[str],
) -> dict:
    if not tables:
        return {"tables": []}
    table_list = ",".join([f"'{t}'" for t in tables])
    sql = (
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns "
        f"WHERE table_schema = '{database}' AND table_name IN ({table_list}) "
        "ORDER BY table_name, ordinal_position"
    )
    output = _run_mysql_query(container, user, password, database, sql)
    rows = _parse_mysql_tsv(output)
    tables_map: dict[str, list[dict]] = {}
    for row in rows:
        tables_map.setdefault(row["table_name"], []).append(
            {"name": row["column_name"], "type": row["data_type"]}
        )
    return {
        "tables": [
            {"name": name, "columns": columns} for name, columns in tables_map.items()
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload tender pack files and extract JSON via OpenAI API")
    parser.add_argument("pack_dir", help="Path to tender pack directory")
    parser.add_argument("--output", default="output.json", help="Output JSON file")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"), help="Model name")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--purpose", default=os.getenv("OPENAI_FILE_PURPOSE", "user_data"))
    parser.add_argument("--web-search", action="store_true")
    parser.add_argument("--mysql-container", default=os.getenv("PIM_MYSQL_CONTAINER", "suisse-bid-match-pim-mysql-1"))
    parser.add_argument("--mysql-user", default=os.getenv("PIM_MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("PIM_MYSQL_PASSWORD", "root"))
    parser.add_argument("--mysql-db", default=os.getenv("PIM_MYSQL_DB", "pim_raw"))
    parser.add_argument(
        "--schema-tables",
        default=os.getenv(
            "PIM_SCHEMA_TABLES",
            "match_products,match_specs,match_certs,match_assets",
        ),
    )
    args = parser.parse_args()
    dspy_web_search = args.web_search

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

    print(f"Calling responses with {len(tender_file_ids)} files to extract raw text...")
    extract_text_prompt = (
        "Read all files and return the raw plain text content only. "
        "No JSON, no summaries, no headings."
    )
    text_response = _call_responses(
        args.base_url,
        api_key,
        args.model,
        extract_text_prompt,
        tender_file_ids,
        user_text="Return the raw text.",
        tools=[{"type": "web_search", "external_web_access": True}] if dspy_web_search else None,
        json_mode=False,
    )
    tender_text = _extract_output_text(text_response)
    debug_dir = BASE_DIR / "runtime" / "dspy_debug"
    ts = int(time.time())
    _write_debug_text(debug_dir, f"dspy_extract_direct_text_{ts}.txt", tender_text)
    web_context = ""
    if dspy_web_search:
        ws_payload = _call_web_search(
            args.base_url,
            api_key,
            args.model,
            "Swiss lighting tender LV Offerte Preisblatt requirements technical parameters",
        )
        _write_debug_json(debug_dir, f"dspy_extract_direct_web_{ts}.json", ws_payload)
        ws_text = _collect_web_search_text(ws_payload)
        if ws_text:
            web_context = "\n\n".join(ws_text)
            _write_debug_text(debug_dir, f"dspy_extract_direct_web_{ts}.txt", web_context)
    print("Calling DSPy to extract tender requirements...")
    requirements_json = _run_dspy_extract_requirements(
        args.model, api_key, tender_text, web_context=web_context
    )

    _write_json(BASE_DIR / "requirements.json", requirements_json)
    schema_tables = [t.strip() for t in args.schema_tables.split(",") if t.strip()]
    print(f"Fetching schema metadata for tables: {', '.join(schema_tables)}")
    schema_metadata = _fetch_schema_metadata(
        args.mysql_container,
        args.mysql_user,
        args.mysql_password,
        args.mysql_db,
        schema_tables,
    )
    _write_json(BASE_DIR / "schema.json", schema_metadata)

    print("Calling LLM to generate SQL queries...")
    web_context = ""
    if dspy_web_search:
        ws_payload = _call_web_search(
            args.base_url,
            api_key,
            args.model,
            "Swiss lighting product parameters hard vs soft constraints IP IK UGR CRI lumen power",
        )
        debug_dir = BASE_DIR / "runtime" / "dspy_debug"
        ts = int(time.time())
        _write_debug_json(debug_dir, f"dspy_sql_web_{ts}.json", ws_payload)
        ws_text = _collect_web_search_text(ws_payload)
        if ws_text:
            web_context = "\n\n".join(ws_text)
            _write_debug_text(debug_dir, f"dspy_sql_web_{ts}.txt", web_context)
    sql_payload = _run_dspy_generate_sql(
        args.model, api_key, requirements_json, schema_metadata, web_context=web_context
    )
    _write_json(BASE_DIR / "sql_queries.json", sql_payload)

    queries = sql_payload.get("queries") or []
    query_results: list[dict] = []
    for item in queries:
        sql = item.get("sql")
        product_key = item.get("product_key")
        if not sql:
            continue
        print(f"Executing SQL for {product_key or 'unknown'}...")
        output = _run_mysql_query(
            args.mysql_container,
            args.mysql_user,
            args.mysql_password,
            args.mysql_db,
            sql,
        )
        rows = _parse_mysql_tsv(output)
        query_results.append(
            {
                "product_key": product_key,
                "sql": sql,
                "rows": rows,
            }
        )
    _write_json(BASE_DIR / "sql_results.json", {"results": query_results})

    print("Calling LLM to format match results...")
    web_context = ""
    if dspy_web_search:
        ws_payload = _call_web_search(
            args.base_url,
            api_key,
            args.model,
            "How to interpret lighting product compliance and match results in tenders",
        )
        debug_dir = BASE_DIR / "runtime" / "dspy_debug"
        ts = int(time.time())
        _write_debug_json(debug_dir, f"dspy_format_web_{ts}.json", ws_payload)
        ws_text = _collect_web_search_text(ws_payload)
        if ws_text:
            web_context = "\n\n".join(ws_text)
            _write_debug_text(debug_dir, f"dspy_format_web_{ts}.txt", web_context)
    response = _run_dspy_format_match(
        args.model,
        api_key,
        requirements_json,
        schema_metadata,
        query_results,
        web_context=web_context,
    )
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(response, ensure_ascii=False)}],
            }
        ]
    }

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (BASE_DIR / output_path).resolve()
    output_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        prompt_result = _extract_output_json(response)
        final_result = _build_final_result(prompt_result)
        _write_json(BASE_DIR / "prompt_result.json", final_result)
    except Exception:
        pass
    print(f"Saved response to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
