from __future__ import annotations

import argparse
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Callable

from .config import load_pipeline_config
from .contracts import (
    SchemaPayload,
    build_step_envelope,
    schema_column_set,
    validate_step2_data,
    validate_step3_data,
    validate_step4_data,
    validate_step5_data,
    validate_step6_data,
    validate_step7_data,
)
from .io_utils import collect_files, ensure_dir, generate_run_id, load_env_file, read_json, write_json
from .kb_step import ensure_vector_store
from .matching import build_step7_prerank_bundle
from .mysql_client import fetch_schema_metadata, parse_mysql_tsv, run_mysql_query
from .openai_client import call_responses, extract_output_json, upload_file
from .sql_builder import build_step4_merged, build_step5_sql


LLM_PROGRESS_PREFIX = "LLM_PROGRESS::"


PIPELINE_STEPS = [
    "step1_kb_bootstrap",
    "step2_extract_requirements",
    "step3_external_field_rules",
    "step4_merge_requirements_hardness",
    "step5_build_sql",
    "step6_execute_sql",
    "step7_rank_candidates",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run novel 7-step tender matching pipeline.")
    parser.add_argument("tender_dir", help="Path to tender folder")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[2] / "pipeline.yaml"),
        help="Path to pipeline.yaml",
    )
    parser.add_argument(
        "--field-rules-json",
        default=str(Path(__file__).resolve().parents[2] / "field_rules.json"),
        help="Path to external Step3 field rules JSON",
    )
    parser.add_argument("--output", default=None, help="Path to final output JSON")
    parser.add_argument("--web-search", action="store_true", help="Enable web_search tool for LLM steps")
    parser.add_argument("--model", default=None, help="Override OpenAI model")
    parser.add_argument("--skip-kb-bootstrap", action="store_true", help="Skip Step1 vector store bootstrap")
    parser.add_argument("--schema-json", default=None, help="Optional prebuilt schema JSON path")
    return parser


def _normalize_step2_raw(raw: dict) -> tuple[list[dict], list[str]]:
    uncertainties = raw.get("uncertainties")
    normalized_uncertainties: list[str] = []
    if isinstance(uncertainties, list):
        for item in uncertainties:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized_uncertainties.append(text)
            elif item is not None:
                normalized_uncertainties.append(str(item))
    elif uncertainties is not None:
        normalized_uncertainties.append(str(uncertainties))

    tender_products = raw.get("tender_products")
    if not isinstance(tender_products, list):
        raise ValueError("Step2 LLM output must contain tender_products list")
    return tender_products, normalized_uncertainties


def _assign_requirement_ids(tender_products: list[dict]) -> None:
    for p_idx, product in enumerate(tender_products):
        if not isinstance(product, dict):
            continue
        product_key = product.get("product_key")
        if not isinstance(product_key, str) or not product_key.strip():
            product_key = f"item_{p_idx + 1:03d}"
            product["product_key"] = product_key
        requirements = product.get("requirements")
        if not isinstance(requirements, list):
            product["requirements"] = []
            continue
        for r_idx, requirement in enumerate(requirements):
            if not isinstance(requirement, dict):
                continue
            requirement_id = requirement.get("requirement_id")
            if not isinstance(requirement_id, str) or not requirement_id.strip():
                requirement["requirement_id"] = f"{product_key}.req_{r_idx + 1:04d}"


def _extract_step3_payload(raw: dict) -> tuple[dict, list[str]]:
    uncertainties: list[str] = []
    raw_uncertainties = raw.get("uncertainties")
    if isinstance(raw_uncertainties, list):
        for item in raw_uncertainties:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    uncertainties.append(text)
            elif item is not None:
                uncertainties.append(str(item))
    elif raw_uncertainties is not None:
        uncertainties.append(str(raw_uncertainties))

    if "field_rules" in raw:
        return {"field_rules": raw.get("field_rules") or []}, uncertainties
    data = raw.get("data")
    if isinstance(data, dict) and "field_rules" in data:
        return {"field_rules": data.get("field_rules") or []}, uncertainties
    raise ValueError("Step3 field rules JSON must contain field_rules at top level or in data")


def _build_step2_prompt(allowed_fields: list[str]) -> str:
    fields_json = json.dumps(allowed_fields, ensure_ascii=False)
    return (
        "You extract structured tender requirements for lighting products from uploaded files.\n"
        "Goal: identify each requested product and map only explicit requirements to allowed schema fields.\n"
        "Source of truth:\n"
        "- Uploaded tender files are the only authority for explicit requirements.\n"
        "- File search or web knowledge may help interpret terminology, abbreviations, units, and field mapping.\n"
        "- Never add, strengthen, or assume a requirement that is not explicitly supported by the uploaded files.\n"
        "Output strict JSON and use exactly this structure:\n"
        "{\n"
        '  "tender_products":[\n'
        "    {\n"
        '      "product_key":"item_001",\n'
        '      "product_name":"<explicit product or line item name>",\n'
        '      "quantity":null,\n'
        '      "requirements":[\n'
        "        {\n"
        '          "field":"<allowed_field>",\n'
        '          "value":"<explicit value or [min,max] range>",\n'
        '          "unit":null,\n'
        '          "source":{"file_name":"<file name>","snippet":"<short supporting snippet>"},\n'
        '          "extraction_confidence":0.0\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "uncertainties":["<short note about ambiguity, conflict, or unmapped requirement>"]\n'
        "}\n"
        "Extraction policy:\n"
        "1) Work schema-first: field must be table.column and must exist in allowed_fields.\n"
        "2) Work evidence-first: every requirement must be backed by source.file_name and a short supporting snippet.\n"
        "3) Precision over recall: when evidence is weak, conflicting, implied, or only supported by outside knowledge, omit the requirement and record the issue in uncertainties.\n"
        "4) Do not output operator, is_hard, hardness_confidence, or operator_confidence in Step2 requirements.\n"
        "5) Extract only parameter names and values or explicit ranges; do not write SQL.\n"
        "6) If multiple files are uploaded, first identify the file or small set of files most likely to contain the authoritative tender product list and parameter schedule.\n"
        "7) Prioritize files that enumerate line items, quantities, product names, requirement tables, or structured parameter columns. In Swiss tender packs, a Leistungsverzeichnis often serves this role, but verify this by content and structure rather than title alone.\n"
        "8) Use that primary list or schedule file to define product boundaries, product_key grouping, product_name, and quantity whenever possible.\n"
        "9) Use supplementary files to confirm, enrich, or clarify the same requested items. Do not create extra tender_products from marketing sheets, catalogs, datasheets, or general background documents unless they clearly define requested tender items.\n"
        "10) If files conflict, prefer the primary list or schedule file for item identity and quantity, use other files for technical clarification when explicit, and record the conflict in uncertainties.\n"
        "11) field cannot repeat under the same product_key. Merge repeated mentions into one best-supported requirement.\n"
        "12) Create one tender_products entry per distinct requested product or line item. Merge corroborating evidence across files only when it clearly refers to the same item.\n"
        "13) quantity must be explicit. If absent or unclear, use null.\n"
        "14) product_name must come from the files. If the files do not name the requested item clearly, use null.\n"
        "15) For a single explicit value, use a scalar. For an explicit closed range, use a two-item array [min, max]. Keep textual enumerations as strings or lists only when explicitly stated.\n"
        "16) Keep unit separate when the files state one. Do not convert units unless the converted value is explicitly written in the files.\n"
        "17) Do not treat example brands, reference products, supplier offers, optional accessories, or background narrative as requirements unless the files clearly make them mandatory for the requested item.\n"
        "18) If a requirement is explicit but no safe allowed_fields mapping exists, omit it from requirements and mention the unmapped concept in uncertainties.\n"
        "File-type guidance:\n"
        "- PDF: inspect headings, schedules, notes, legends, footnotes, and prose around tables; important constraints may appear in sentences rather than cells.\n"
        "- DOCX: use both narrative sections and embedded tables; table headers, merged cells, and nearby headings often define parameter meaning.\n"
        "- XLSX: use sheet names, header rows, units columns, merged section labels, and row context when mapping each value.\n"
        "Quality checks before finishing:\n"
        "- No non-schema fields.\n"
        "- No duplicate field within a product.\n"
        "- No invented requirements.\n"
        "- Keep snippets short and specific.\n"
        f"allowed_fields:\n{fields_json}\n"
    )


def _build_step7_prompt() -> str:
    return (
        "You rerank pre-shortlisted candidate products for each tender product.\n"
        "Input is a compressed shortlist payload created after deterministic pre-ranking.\n"
        "The input payload contains a products array. Produce exactly one match_results object for each input product_key, in the same order as the input products array.\n"
        "Output strict JSON only, with exactly this structure:\n"
        "{\n"
        '  "match_results":[\n'
        "    {\n"
        '      "product_key":"item_001",\n'
        '      "candidates":[\n'
        "        {\n"
        '          "rank":1,\n'
        '          "db_product_id":"<candidate id>",\n'
        '          "db_product_name":"<candidate name>",\n'
        '          "passes_hard":true,\n'
        '          "soft_match_score":0.0,\n'
        '          "matched_soft_constraints":["<soft_field>"],\n'
        '          "unmet_soft_constraints":["<soft_field>"],\n'
        '          "explanation":"<short soft-fit explanation>"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "uncertainties":[]\n'
        "}\n"
        "Ranking policy:\n"
        "1) Treat each product_key independently. Do not compare candidates across different requested products.\n"
        "2) Only rank the shortlisted_candidates provided in the input. Do not invent, add, or reference candidates outside the shortlist.\n"
        "3) Use pre_rank_score and numeric_field_details as structured evidence from deterministic numeric pre-ranking.\n"
        "4) Use string_field_values and string_soft_constraints to refine ranking based on string semantics inside the shortlist.\n"
        "5) Hard constraints are already filtered upstream. Do not relax, reinterpret, or penalize them again.\n"
        "6) soft_match_score must be numeric in the range [0,1], where higher means better overall soft-constraint fit.\n"
        "7) matched_soft_constraints and unmet_soft_constraints must contain only shortlisted soft-constraint field names that you can justify from the provided shortlist payload.\n"
        "8) Keep explanation short, concrete, and focused on soft-constraint fit only.\n"
        "9) If a product has no shortlisted candidates, return an empty candidates list for that product_key.\n"
        "10) Respect the shortlist evidence; do not invent unsupported numeric comparisons or missing string facts.\n"
        "11) Assign unique integer ranks starting at 1 within each product_key.\n"
        "12) Never output the same product_key twice in match_results. Do not split one product_key across multiple objects.\n"
        "13) Before finishing, verify that the set and count of product_key values in match_results exactly match the input products array: no duplicates, no omissions, no extras.\n"
    )


def _build_step7_user_text(shortlist_payload: dict) -> str:
    return "step7_shortlist_json:\n" + json.dumps(shortlist_payload, ensure_ascii=False)


def _upload_tender_files(base_url: str, api_key: str, purpose: str, tender_files: list[Path]) -> list[str]:
    file_ids: list[str] = []
    for path in tender_files:
        if path.stat().st_size <= 0:
            continue
        try:
            file_id = upload_file(base_url, api_key, path, purpose)
        except Exception as exc:
            if "file is empty" in str(exc).strip().lower():
                continue
            raise
        file_ids.append(file_id)
    return file_ids


def _write_step(run_dir: Path, step_name: str, payload: dict) -> None:
    write_json(run_dir / f"{step_name}.json", payload)


def _write_not_run_steps(run_dir: Path, run_id: str, step_names: list[str], *, reason: str) -> None:
    for step_name in step_names:
        step_path = run_dir / f"{step_name}.json"
        if step_path.exists():
            continue
        payload = build_step_envelope(
            step=step_name,
            run_id=run_id,
            status="partial",
            data={"state": "not_run"},
            uncertainties=[reason],
        )
        _write_step(run_dir, step_name, payload)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


@dataclass
class LLMExecutionTrace:
    step_name: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    response_received: bool = False
    failure_message: str | None = None
    fallback_used: bool = False
    reasoning_text_parts: list[str] = dataclass_field(default_factory=list)
    stream_event_counts: dict[str, int] = dataclass_field(default_factory=dict)
    status_events: list[str] = dataclass_field(default_factory=list)

    def record_status(self, status: str, *, message: str | None = None) -> None:
        self.status_events.append(status)
        if status == "llm_request_started" and self.started_at is None:
            self.started_at = _utcnow()
            return
        if status == "llm_response_received":
            self.response_received = True
            if self.finished_at is None:
                self.finished_at = _utcnow()
            return
        if status == "llm_request_failed":
            if isinstance(message, str) and message.strip():
                self.failure_message = message.strip()
            if self.finished_at is None:
                self.finished_at = _utcnow()

    def record_stream_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("kind") or "unknown")
        self.stream_event_counts[kind] = self.stream_event_counts.get(kind, 0) + 1
        if kind in {"reasoning_summary_delta", "reasoning_summary"}:
            text = event.get("text")
            if isinstance(text, str) and text:
                self.reasoning_text_parts.append(text)

    def mark_fallback_used(self) -> None:
        self.fallback_used = True

    def to_payload(self) -> dict[str, Any]:
        if self.finished_at is None and (self.response_received or self.failure_message):
            self.finished_at = _utcnow()
        final_status = "failed" if self.failure_message else "succeeded"
        duration_ms: int | None = None
        if self.started_at is not None and self.finished_at is not None:
            duration_ms = max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))
        reasoning_text = "".join(self.reasoning_text_parts).strip()
        return {
            "step_name": self.step_name,
            "request_started_at": _to_iso(self.started_at),
            "request_finished_at": _to_iso(self.finished_at),
            "duration_ms": duration_ms,
            "final_status": final_status,
            "response_received": self.response_received,
            "fallback_used": self.fallback_used,
            "failure_message": self.failure_message,
            "reasoning_summary": reasoning_text or None,
            "reasoning_chars": len(reasoning_text),
            "stream_event_counts": self.stream_event_counts,
            "status_events": self.status_events,
        }


def _emit_llm_progress(run_id: str, step_name: str, payload: dict[str, Any]) -> None:
    event = {"run_id": run_id, "step_name": step_name}
    event.update(payload)
    try:
        encoded = json.dumps(event, ensure_ascii=False)
    except Exception:
        encoded = json.dumps(
            {
                "run_id": run_id,
                "step_name": step_name,
                "kind": "status",
                "status": "serialize_failed",
                "message": str(payload),
            },
            ensure_ascii=False,
        )
    print(f"{LLM_PROGRESS_PREFIX}{encoded}", flush=True)


def _emit_llm_status(
    run_id: str,
    step_name: str,
    trace: LLMExecutionTrace,
    *,
    status: str,
    message: str | None = None,
) -> None:
    trace.record_status(status, message=message)
    payload: dict[str, Any] = {"kind": "status", "status": status}
    if message:
        payload["message"] = message
    _emit_llm_progress(run_id, step_name, payload)


def _emit_llm_execution_summary(run_id: str, trace: LLMExecutionTrace) -> dict[str, Any]:
    summary = trace.to_payload()
    _emit_llm_progress(
        run_id,
        trace.step_name,
        {
            "kind": "execution_summary",
            "summary": summary,
        },
    )
    return summary


def _build_llm_stream_notifier(
    run_id: str,
    step_name: str,
    trace: LLMExecutionTrace,
) -> tuple[Callable[[dict[str, Any]], None], Callable[[], None]]:
    buffered_text = ""
    buffered_event_type: str | None = None

    def _flush() -> None:
        nonlocal buffered_text, buffered_event_type
        if not buffered_text:
            return
        _emit_llm_progress(
            run_id,
            step_name,
            {
                "kind": "reasoning_summary_delta",
                "event_type": buffered_event_type or "response.reasoning_summary_text.delta",
                "text": buffered_text,
            },
        )
        trace.record_stream_event(
            {
                "kind": "reasoning_summary_delta",
                "event_type": buffered_event_type or "response.reasoning_summary_text.delta",
                "text": buffered_text,
            }
        )
        buffered_text = ""
        buffered_event_type = None

    def _notify(event: dict[str, Any]) -> None:
        nonlocal buffered_text, buffered_event_type
        kind = event.get("kind")
        if kind == "reasoning_summary_delta":
            text = event.get("text")
            if not isinstance(text, str) or not text:
                return
            buffered_text += text
            current_event_type = event.get("event_type")
            if isinstance(current_event_type, str) and current_event_type:
                buffered_event_type = current_event_type
            if len(buffered_text) >= 120 or "\n" in text:
                _flush()
            return
        _flush()
        trace.record_stream_event(event)
        _emit_llm_progress(run_id, step_name, event)

    return _notify, _flush


def _envelope_error(step: str, run_id: str, code: str, message: str, details: dict | None = None) -> dict:
    return build_step_envelope(
        step=step,
        run_id=run_id,
        status="error",
        data={},
        errors=[
            {
                "code": code,
                "message": message,
                "retryable": False,
                "details": details or {},
            }
        ],
    )


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[3]
    src_root = Path(__file__).resolve().parents[2]

    load_env_file(Path.cwd() / ".env")
    load_env_file(project_root / ".env")
    if src_root != project_root:
        load_env_file(src_root / ".env")

    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 2
    config = load_pipeline_config(config_path)

    openai_cfg = config["openai"]
    kb_cfg = config["kb"]
    db_cfg = config["db"]
    runtime_cfg = config["runtime"]

    base_url = os.getenv("OPENAI_BASE_URL", openai_cfg["base_url"]).rstrip("/")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2
    model = args.model or os.getenv("OPENAI_MODEL", openai_cfg["model"])
    file_purpose = os.getenv("OPENAI_FILE_PURPOSE", openai_cfg["file_purpose"])
    enable_web_search = bool(args.web_search or openai_cfg.get("enable_web_search", False))

    db_container = os.getenv("PIM_MYSQL_CONTAINER", db_cfg["container"])
    db_user = os.getenv("PIM_MYSQL_USER", db_cfg["user"])
    db_password = os.getenv("PIM_MYSQL_PASSWORD", db_cfg["password"])
    db_name = os.getenv("PIM_MYSQL_DB", db_cfg["database"])
    schema_tables = list(db_cfg.get("tables") or ["vw_bid_products", "vw_bid_specs"])
    schema_tables = [table.strip() for table in schema_tables if table.strip()]
    join_key = str(db_cfg.get("join_key") or "product_id").strip()

    tender_dir = Path(args.tender_dir).resolve()
    if not tender_dir.exists() or not tender_dir.is_dir():
        print(f"Tender dir not found: {tender_dir}", file=sys.stderr)
        return 2

    run_id = generate_run_id()
    runtime_root = Path(runtime_cfg.get("output_dir") or "runtime")
    if not runtime_root.is_absolute():
        runtime_root = (src_root / runtime_root).resolve()
    run_dir = ensure_dir(runtime_root / run_id)

    vector_store_id: str | None = None

    # STEP1
    if args.skip_kb_bootstrap:
        step1_payload = build_step_envelope(
            step="step1_kb_bootstrap",
            run_id=run_id,
            status="partial",
            data={
                "kb_key": kb_cfg["kb_key"],
                "source_dir": kb_cfg["source_dir"],
                "source_file_count": 0,
                "vector_store": {"id": None, "name": kb_cfg["vector_store_name"], "reused": False, "status": "skipped"},
                "upload_summary": {"uploaded_files": 0, "skipped_files": 0},
            },
            uncertainties=["KB bootstrap skipped by --skip-kb-bootstrap"],
        )
        _write_step(run_dir, "step1_kb_bootstrap", step1_payload)
    else:
        try:
            step1_data = ensure_vector_store(
                base_url=base_url,
                api_key=api_key,
                kb_key=kb_cfg["kb_key"],
                vector_store_name=kb_cfg["vector_store_name"],
                source_dir=Path(kb_cfg["source_dir"]),
                file_purpose=file_purpose,
                description=kb_cfg.get("description"),
            )
            vector_store_obj = step1_data.get("vector_store")
            if isinstance(vector_store_obj, dict):
                maybe_id = vector_store_obj.get("id")
                if isinstance(maybe_id, str) and maybe_id.strip():
                    vector_store_id = maybe_id.strip()
            step1_payload = build_step_envelope(
                step="step1_kb_bootstrap",
                run_id=run_id,
                data=step1_data,
                status="ok",
            )
            _write_step(run_dir, "step1_kb_bootstrap", step1_payload)
        except Exception as exc:
            payload = _envelope_error(
                "step1_kb_bootstrap",
                run_id,
                "KB_BOOTSTRAP_FAILED",
                str(exc),
            )
            _write_step(run_dir, "step1_kb_bootstrap", payload)
            _write_not_run_steps(
                run_dir,
                run_id,
                PIPELINE_STEPS[1:],
                reason="Pipeline stopped after Step1 failure.",
            )
            print(f"Step1 failed: {exc}", file=sys.stderr)
            return 2

    # Schema source used by Step2+Step3+Step5
    try:
        if args.schema_json:
            schema_payload = read_json(Path(args.schema_json).resolve())
        else:
            schema_payload = fetch_schema_metadata(
                db_container,
                db_user,
                db_password,
                db_name,
                schema_tables,
            )
        schema_payload = SchemaPayload.model_validate(schema_payload).model_dump(mode="python")
        schema_snapshot_payload = build_step_envelope(
            step="schema_snapshot",
            run_id=run_id,
            status="ok",
            data=schema_payload,
        )
        _write_step(run_dir, "schema_snapshot", schema_snapshot_payload)
    except Exception as exc:
        step_error = _envelope_error(
            "schema_snapshot",
            run_id,
            "SCHEMA_LOAD_FAILED",
            str(exc),
        )
        _write_step(run_dir, "schema_snapshot", step_error)
        _write_not_run_steps(
            run_dir,
            run_id,
            PIPELINE_STEPS[1:],
            reason="Pipeline stopped after schema loading failure.",
        )
        print(f"Schema load failed: {exc}", file=sys.stderr)
        return 2

    allowed_fields = schema_column_set(schema_payload)
    allowed_tables = {table["name"] for table in schema_payload.get("tables", []) if isinstance(table, dict)}

    # STEP2
    step2_trace = LLMExecutionTrace("step2_extract_requirements")
    step2_stream_flush: Callable[[], None] = lambda: None
    try:
        tender_files = collect_files(tender_dir)
        if not tender_files:
            raise RuntimeError("No supported tender files found")
        tender_file_ids = _upload_tender_files(base_url, api_key, file_purpose, tender_files)
        if not tender_file_ids:
            raise RuntimeError("No valid tender files uploaded after skipping empty files")
        tools: list[dict] = []
        include: list[str] = []
        if vector_store_id:
            tools.append(
                {
                    "type": "file_search",
                    "vector_store_ids": [vector_store_id],
                    "max_num_results": int(kb_cfg.get("max_num_results") or 12),
                }
            )
            include.append("file_search_call.results")
        if enable_web_search:
            tools.append({"type": "web_search", "external_web_access": True})
            include.append("web_search_call.results")

        stream_notify, step2_stream_flush = _build_llm_stream_notifier(
            run_id,
            "step2_extract_requirements",
            step2_trace,
        )
        _emit_llm_status(
            run_id,
            "step2_extract_requirements",
            step2_trace,
            status="llm_request_started",
        )
        response = call_responses(
            base_url,
            api_key,
            model,
            system_prompt=_build_step2_prompt(sorted(allowed_fields)),
            user_text="Extract tender lighting requirement parameters and return strict JSON as required.",
            file_ids=tender_file_ids,
            tools=tools or None,
            include=include or None,
            json_mode=True,
            on_stream_event=stream_notify,
        )
        step2_stream_flush()
        _emit_llm_status(
            run_id,
            "step2_extract_requirements",
            step2_trace,
            status="llm_response_received",
        )
        raw_step2 = extract_output_json(response)
        tender_products, llm_uncertainties = _normalize_step2_raw(raw_step2)
        _assign_requirement_ids(tender_products)
        dropped_non_schema = 0
        for product in tender_products:
            if not isinstance(product, dict):
                continue
            requirements = product.get("requirements")
            if not isinstance(requirements, list):
                product["requirements"] = []
                continue
            filtered_requirements: list[dict] = []
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    continue
                field = requirement.get("field")
                if not isinstance(field, str) or field not in allowed_fields:
                    dropped_non_schema += 1
                    continue
                filtered_requirements.append(requirement)
            product["requirements"] = filtered_requirements
        if dropped_non_schema:
            llm_uncertainties.append(
                f"Dropped {dropped_non_schema} Step2 requirements with non-schema fields."
            )
        step2_data = {
            "schema_snapshot": schema_payload,
            "tender_products": tender_products,
            "llm_execution": _emit_llm_execution_summary(run_id, step2_trace),
        }
        step2_data = validate_step2_data(step2_data)

        step2_payload = build_step_envelope(
            step="step2_extract_requirements",
            run_id=run_id,
            data=step2_data,
            uncertainties=llm_uncertainties,
            status="ok",
        )
        _write_step(run_dir, "step2_extract_requirements", step2_payload)
    except Exception as exc:
        try:
            step2_stream_flush()
        except Exception:
            pass
        _emit_llm_status(
            run_id,
            "step2_extract_requirements",
            step2_trace,
            status="llm_request_failed",
            message=str(exc),
        )
        _emit_llm_execution_summary(run_id, step2_trace)
        payload = _envelope_error(
            "step2_extract_requirements",
            run_id,
            "STEP2_FAILED",
            str(exc),
            {"traceback": traceback.format_exc(limit=3)},
        )
        _write_step(run_dir, "step2_extract_requirements", payload)
        _write_not_run_steps(
            run_dir,
            run_id,
            PIPELINE_STEPS[2:],
            reason="Pipeline stopped after Step2 failure.",
        )
        print(f"Step2 failed: {exc}", file=sys.stderr)
        return 2

    # STEP3 (external JSON only)
    try:
        rules_path = Path(args.field_rules_json).resolve()
        if not rules_path.exists():
            raise FileNotFoundError(f"Step3 field rules file not found: {rules_path}")
        raw_rules = read_json(rules_path)
        step3_data_raw, step3_uncertainties = _extract_step3_payload(raw_rules)
        step3_data = validate_step3_data(step3_data_raw, allowed_fields=allowed_fields)
        step3_payload = build_step_envelope(
            step="step3_external_field_rules",
            run_id=run_id,
            data=step3_data,
            uncertainties=step3_uncertainties,
            status="ok",
        )
        _write_step(run_dir, "step3_external_field_rules", step3_payload)
    except Exception as exc:
        payload = _envelope_error(
            "step3_external_field_rules",
            run_id,
            "STEP3_FAILED",
            str(exc),
            {"traceback": traceback.format_exc(limit=3)},
        )
        _write_step(run_dir, "step3_external_field_rules", payload)
        _write_not_run_steps(
            run_dir,
            run_id,
            PIPELINE_STEPS[3:],
            reason="Pipeline stopped after Step3 failure.",
        )
        print(f"Step3 failed: {exc}", file=sys.stderr)
        return 2

    # STEP4 (merge patch)
    try:
        step4_data = build_step4_merged(step2_data, step3_data)
        step4_data = validate_step4_data(step4_data)
        step4_uncertainties = []
        if step4_data.get("skipped_requirements"):
            step4_uncertainties.append(
                f"Skipped {len(step4_data['skipped_requirements'])} requirements missing Step3 field rules."
            )
        step4_payload = build_step_envelope(
            step="step4_merge_requirements_hardness",
            run_id=run_id,
            data=step4_data,
            uncertainties=step4_uncertainties,
            status="ok",
        )
        _write_step(run_dir, "step4_merge_requirements_hardness", step4_payload)
    except Exception as exc:
        payload = _envelope_error(
            "step4_merge_requirements_hardness",
            run_id,
            "STEP4_FAILED",
            str(exc),
            {"traceback": traceback.format_exc(limit=3)},
        )
        _write_step(run_dir, "step4_merge_requirements_hardness", payload)
        _write_not_run_steps(
            run_dir,
            run_id,
            PIPELINE_STEPS[4:],
            reason="Pipeline stopped after Step4 failure.",
        )
        print(f"Step4 failed: {exc}", file=sys.stderr)
        return 2

    # STEP5 (SQL build)
    try:
        step5_data = build_step5_sql(step4_data, schema_payload, join_key=join_key)
        step5_data = validate_step5_data(step5_data, allowed_tables=allowed_tables)
        step5_payload = build_step_envelope(
            step="step5_build_sql",
            run_id=run_id,
            data=step5_data,
            status="ok",
        )
        _write_step(run_dir, "step5_build_sql", step5_payload)
    except Exception as exc:
        payload = _envelope_error(
            "step5_build_sql",
            run_id,
            "STEP5_FAILED",
            str(exc),
            {"traceback": traceback.format_exc(limit=3)},
        )
        _write_step(run_dir, "step5_build_sql", payload)
        _write_not_run_steps(
            run_dir,
            run_id,
            PIPELINE_STEPS[5:],
            reason="Pipeline stopped after Step5 failure.",
        )
        print(f"Step5 failed: {exc}", file=sys.stderr)
        return 2

    # STEP6 (SQL execute)
    try:
        results: list[dict] = []
        for query in step5_data.get("queries", []):
            query_id = query.get("query_id")
            product_key = query.get("product_key")
            sql = query.get("sql")
            if not isinstance(query_id, str) or not isinstance(product_key, str) or not isinstance(sql, str):
                continue
            output, elapsed_ms = run_mysql_query(db_container, db_user, db_password, db_name, sql)
            rows = parse_mysql_tsv(output)
            results.append(
                {
                    "query_id": query_id,
                    "product_key": product_key,
                    "sql": sql,
                    "row_count": len(rows),
                    "elapsed_ms": elapsed_ms,
                    "rows": rows,
                }
            )
        step6_data = validate_step6_data({"results": results})
        step6_payload = build_step_envelope(
            step="step6_execute_sql",
            run_id=run_id,
            data=step6_data,
            status="ok",
        )
        _write_step(run_dir, "step6_execute_sql", step6_payload)
    except Exception as exc:
        payload = _envelope_error(
            "step6_execute_sql",
            run_id,
            "STEP6_FAILED",
            str(exc),
            {"traceback": traceback.format_exc(limit=3)},
        )
        _write_step(run_dir, "step6_execute_sql", payload)
        _write_not_run_steps(
            run_dir,
            run_id,
            PIPELINE_STEPS[6:],
            reason="Pipeline stopped after Step6 failure.",
        )
        print(f"Step6 failed: {exc}", file=sys.stderr)
        return 2

    # STEP7 (LLM rank, fallback to deterministic)
    step7_uncertainties: list[str] = []
    step7_trace = LLMExecutionTrace("step7_rank_candidates")
    step7_stream_flush: Callable[[], None] = lambda: None
    step7_bundle = build_step7_prerank_bundle(step4_data, step6_data)
    step7_llm_input = step7_bundle.get("llm_input") or {"products": []}
    step7_pre_rank_summary = step7_bundle.get("pre_rank_summary")
    fallback_payload = step7_bundle.get("fallback_payload") or {"match_results": []}
    try:
        try:
            tools: list[dict] = []
            include: list[str] = []
            if vector_store_id:
                tools.append(
                    {
                        "type": "file_search",
                        "vector_store_ids": [vector_store_id],
                        "max_num_results": int(kb_cfg.get("max_num_results") or 12),
                    }
                )
                include.append("file_search_call.results")
            if enable_web_search:
                tools.append({"type": "web_search", "external_web_access": True})
                include.append("web_search_call.results")

            user_text = _build_step7_user_text(step7_llm_input)
            stream_notify, step7_stream_flush = _build_llm_stream_notifier(
                run_id,
                "step7_rank_candidates",
                step7_trace,
            )
            _emit_llm_status(
                run_id,
                "step7_rank_candidates",
                step7_trace,
                status="llm_request_started",
            )
            response = call_responses(
                base_url,
                api_key,
                model,
                system_prompt=_build_step7_prompt(),
                user_text=user_text,
                file_ids=[],
                tools=tools or None,
                include=include or None,
                json_mode=True,
                on_stream_event=stream_notify,
            )
            step7_stream_flush()
            _emit_llm_status(
                run_id,
                "step7_rank_candidates",
                step7_trace,
                status="llm_response_received",
            )
            raw_step7 = extract_output_json(response)
            raw_unc = raw_step7.get("uncertainties")
            if isinstance(raw_unc, list):
                for item in raw_unc:
                    if isinstance(item, str) and item.strip():
                        step7_uncertainties.append(item.strip())
                    elif item is not None:
                        step7_uncertainties.append(str(item))
            step7_data = validate_step7_data(
                {
                    "match_results": raw_step7.get("match_results", []),
                    "pre_rank_summary": step7_pre_rank_summary,
                    "llm_execution": _emit_llm_execution_summary(run_id, step7_trace),
                }
            )
        except Exception as exc:
            try:
                step7_stream_flush()
            except Exception:
                pass
            _emit_llm_status(
                run_id,
                "step7_rank_candidates",
                step7_trace,
                status="llm_request_failed",
                message=str(exc),
            )
            step7_trace.mark_fallback_used()
            step7_uncertainties.append(
                f"Step7 LLM ranking failed and fallback ranking was used: {exc}"
            )
            fallback_payload["llm_execution"] = _emit_llm_execution_summary(run_id, step7_trace)
            step7_data = validate_step7_data(fallback_payload)

        step7_payload = build_step_envelope(
            step="step7_rank_candidates",
            run_id=run_id,
            data=step7_data,
            uncertainties=step7_uncertainties,
            status="ok",
        )
        _write_step(run_dir, "step7_rank_candidates", step7_payload)
    except Exception as exc:
        step7_error = _envelope_error(
            "step7_rank_candidates",
            run_id,
            "STEP7_FAILED",
            str(exc),
            {"traceback": traceback.format_exc(limit=3)},
        )
        _write_step(run_dir, "step7_rank_candidates", step7_error)
        print(f"Step7 failed: {exc}", file=sys.stderr)
        return 2

    step_files = {step_name: str((run_dir / f"{step_name}.json").resolve()) for step_name in PIPELINE_STEPS}
    step_files["schema_snapshot"] = str((run_dir / "schema_snapshot.json").resolve())
    write_json(
        run_dir / "step_index.json",
        {
            "run_id": run_id,
            "runtime_dir": str(run_dir),
            "step_files": step_files,
        },
    )

    # Final output
    final_payload = {
        "run_id": run_id,
        "runtime_dir": str(run_dir),
        "tender_products": step4_data.get("tender_products", []),
        "skipped_requirements": step4_data.get("skipped_requirements", []),
        "match_results": step7_data.get("match_results", []),
        "uncertainties": step7_uncertainties,
    }

    output_path = Path(args.output).resolve() if args.output else (run_dir / "final_output.json")
    write_json(output_path, final_payload)
    print(f"Saved final output to {output_path}")
    return 0
