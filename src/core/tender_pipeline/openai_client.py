from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

import requests


def _should_disable_json_format(resp: requests.Response) -> bool:
    if resp.status_code not in {400, 422}:
        return False
    text = (resp.text or "").lower()
    markers = (
        "text.format",
        "response_format",
        "json_object",
        "json_schema",
    )
    return any(marker in text for marker in markers)


def upload_file(
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
                time.sleep(2**attempt)
                continue
        if resp.status_code in {429, 500, 502, 503, 504}:
            time.sleep(2**attempt)
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


def call_responses(
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
    payload_base: dict = {
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
        payload_base["tools"] = tools
    if include:
        payload_base["include"] = include

    use_json_format = bool(json_mode)
    last_error = None
    for attempt in range(4):
        payload = dict(payload_base)
        if use_json_format:
            payload["text"] = {"format": {"type": "json_object"}}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=600)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2**attempt)
            continue
        if resp.status_code in {429, 500, 502, 503, 504}:
            time.sleep(2**attempt)
            continue
        if resp.status_code >= 400:
            if use_json_format and _should_disable_json_format(resp):
                use_json_format = False
                continue
            raise RuntimeError(f"responses call failed: {resp.status_code} {resp.text}")
        return resp.json()
    if last_error:
        raise RuntimeError(f"responses call failed: {last_error}")
    raise RuntimeError("responses call failed: service unavailable")


def call_web_search(
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


def collect_web_search_text(response: dict) -> List[str]:
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


def _iter_output_texts(response: dict):
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                yield content["text"]


def _unwrap_code_fence(raw: str) -> str:
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return raw
    lines = stripped.splitlines()
    if len(lines) < 3:
        return raw
    if not lines[0].startswith("```") or not lines[-1].startswith("```"):
        return raw
    return "\n".join(lines[1:-1]).strip()


def extract_output_json(response: dict) -> dict:
    last_error: Exception | None = None
    for text in _iter_output_texts(response):
        candidates = [text, _unwrap_code_fence(text)]
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(text[start : end + 1])

        for idx, candidate in enumerate(candidates):
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                return load_json_with_repair(candidate, f"response_output_json[{idx}]")
            except Exception as exc:
                last_error = exc
                continue
    if last_error:
        raise RuntimeError(f"No valid output JSON found in response: {last_error}") from last_error
    raise RuntimeError("No output_text JSON found in response")


def extract_output_text(response: dict) -> str:
    for text in _iter_output_texts(response):
        return text
    raise RuntimeError("No output_text found in response")


def load_json_with_repair(raw_text: str, payload_name: str):
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
        except Exception as exc:
            raise RuntimeError(
                f"{payload_name} is not valid JSON and json_repair is unavailable"
            ) from exc

        repaired_text = repair_json(raw_text)
        try:
            return json.loads(repaired_text)
        except json.JSONDecodeError as exc:
            snippet = raw_text[:500].replace("\n", "\\n")
            raise RuntimeError(
                f"{payload_name} is not valid JSON and auto-repair failed. Snippet: {snippet}"
            ) from exc
