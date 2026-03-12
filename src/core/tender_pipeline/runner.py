from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from kb.kb_builder import DEFAULT_BASE as KB_DEFAULT_BASE
from kb.preprocess import DEFAULT_SRC as KB_DEFAULT_SRC
from kb.vector_store_sync import DEFAULT_STORE_NAME as KB_DEFAULT_STORE_NAME

from validator.contracts import (
    validate_hardness_review_payload,
    validate_prompt_result_payload,
    validate_requirements_payload,
    validate_reviewed_requirements_payload,
    validate_schema_payload,
    validate_sql_queries_payload,
)

from .article_context import build_article_reference_context
from .constants import (
    ARTICLE_MULTI_RECORD_PATH,
    ARTICLE_SINGLE_RECORD_PATH,
    BASE_DIR,
)
from .io_utils import (
    build_final_result,
    collect_files,
    load_env_file,
    upload_tender_files,
    write_json,
)
from .kb_bootstrap import ensure_kb_vector_store
from .matching import build_match_from_candidates
from .mysql_client import fetch_schema_metadata, parse_mysql_tsv, run_mysql_query
from .openai_client import (
    call_responses,
    extract_output_json,
)
from .requirements_utils import (
    merge_alignment_into_reviewed_requirements,
    merge_hardness_review_into_requirements,
    sanitize_hardness_review_payload,
    sanitize_requirements_payload,
)
from .runtime_debug import write_debug_json, write_debug_text
from .sql_builder import build_hard_only_sql_queries


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--skip-kb-bootstrap",
        action="store_true",
        help="Skip KB vector store check/build/upload before tender pipeline",
    )
    parser.add_argument(
        "--kb-src",
        default=str(KB_DEFAULT_SRC),
        help="Raw KB source directory for one-shot preprocess/build when store is missing",
    )
    parser.add_argument(
        "--kb-base-dir",
        default=str(KB_DEFAULT_BASE),
        help="Local KB work directory containing upload_corpus_kb and reports_kb",
    )
    parser.add_argument(
        "--kb-vector-store-name",
        default=KB_DEFAULT_STORE_NAME,
        help="KB vector store name",
    )
    parser.add_argument(
        "--kb-key",
        default="lighting_kb",
        help="KB logical key stored in vector store metadata",
    )
    parser.add_argument(
        "--kb-description",
        default="Preprocessed lighting knowledge base for tender matching.",
        help="Description for created KB vector store",
    )
    parser.add_argument(
        "--kb-low-text-threshold",
        type=int,
        default=20,
        help="Drop low-text PDFs below this char threshold when building KB",
    )
    parser.add_argument(
        "--kb-force-rebuild-local",
        action="store_true",
        help="Force rebuild local KB artifacts when vector store is missing",
    )
    parser.add_argument(
        "--kb-batch-size",
        type=int,
        default=100,
        help="File batch size for KB vector store upload",
    )
    parser.add_argument(
        "--kb-max-files",
        type=int,
        default=None,
        help="Optional max files for KB upload (debug/testing)",
    )
    parser.add_argument(
        "--kb-poll-interval-sec",
        type=int,
        default=5,
        help="Polling interval for KB vector store file batch status",
    )
    parser.add_argument(
        "--kb-wait-timeout-sec",
        type=int,
        default=3600,
        help="Timeout for each KB vector store file batch",
    )
    parser.add_argument(
        "--kb-file-purpose",
        default=os.getenv("OPENAI_FILE_PURPOSE", "user_data"),
        help="Files API purpose for KB upload",
    )
    parser.add_argument(
        "--skip-field-alignment",
        action="store_true",
        help="Skip LLM field-alignment stage before SQL generation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    cwd_env = Path.cwd() / ".env"
    script_env = Path(__file__).resolve().parents[2] / ".env"
    load_env_file(cwd_env)
    if script_env != cwd_env:
        load_env_file(script_env)

    parser = build_parser()
    args = parser.parse_args(argv)
    dspy_web_search = args.web_search

    if args.base_url:
        os.environ["OPENAI_BASE_URL"] = args.base_url.rstrip("/")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2

    pack_dir = Path(args.pack_dir).resolve()
    if not pack_dir.exists():
        print(f"pack_dir not found: {pack_dir}", file=sys.stderr)
        return 2

    tender_files = collect_files(pack_dir)
    if not tender_files:
        print("No supported files found in pack", file=sys.stderr)
        return 2

    kb_vector_store_id: str | None = None

    if not args.skip_kb_bootstrap:
        print("Checking KB vector store under current API key...")
        try:
            kb_summary = ensure_kb_vector_store(
                src_dir=Path(args.kb_src),
                base_dir=Path(args.kb_base_dir),
                vector_store_name=args.kb_vector_store_name,
                kb_key=args.kb_key,
                description=args.kb_description,
                low_text_threshold=max(1, args.kb_low_text_threshold),
                force_rebuild_local=args.kb_force_rebuild_local,
                batch_size=max(1, args.kb_batch_size),
                file_purpose=args.kb_file_purpose,
                max_files=args.kb_max_files,
                poll_interval_sec=max(1, args.kb_poll_interval_sec),
                wait_timeout_sec=max(60, args.kb_wait_timeout_sec),
            )
            write_json(BASE_DIR / "kb_bootstrap_summary.json", kb_summary)
            print(f"KB bootstrap status: {kb_summary.get('status')}")
            vector_store_obj = kb_summary.get("vector_store")
            if isinstance(vector_store_obj, dict):
                maybe_vs_id = vector_store_obj.get("id")
                if isinstance(maybe_vs_id, str) and maybe_vs_id.strip():
                    kb_vector_store_id = maybe_vs_id.strip()
        except Exception as exc:
            print(f"KB bootstrap failed: {exc}", file=sys.stderr)
            return 2
    else:
        print("Skipping KB bootstrap step.")

    tender_file_ids = upload_tender_files(args.base_url, api_key, args.purpose, tender_files)
    if not tender_file_ids:
        print("No tender files uploaded", file=sys.stderr)
        return 2

    debug_dir = BASE_DIR / "runtime" / "dspy_debug"
    ts = int(time.time())
    article_reference_context = build_article_reference_context(
        ARTICLE_SINGLE_RECORD_PATH,
        ARTICLE_MULTI_RECORD_PATH,
    )
    if article_reference_context:
        write_debug_text(debug_dir, f"dspy_extract_reference_{ts}.txt", article_reference_context)
    else:
        print(
            "Warning: article reference context unavailable; continuing without articles_* guidance.",
            file=sys.stderr,
        )

    print("Calling Responses to extract tender requirements from uploaded files...")
    from dspy_program.signatures import (
        AlignRequirementsToSchemaSig,
        ExtractRequirementsSig,
        ReviewHardnessSig,
    )

    extract_prompt = (ExtractRequirementsSig.__doc__ or "").strip()
    extract_sections = [extract_prompt]
    if article_reference_context:
        extract_sections.append(f"article_reference_context:\n{article_reference_context}")
    extract_system_prompt = "\n\n".join(section for section in extract_sections if section)

    extract_tools: list[dict] = []
    extract_include: list[str] = []
    if kb_vector_store_id:
        extract_tools.append(
            {
                "type": "file_search",
                "vector_store_ids": [kb_vector_store_id],
                "max_num_results": 12,
            }
        )
        extract_include.append("file_search_call.results")
    if dspy_web_search:
        extract_tools.append({"type": "web_search", "external_web_access": True})
        extract_include.append("web_search_call.results")

    extraction_response = call_responses(
        args.base_url,
        api_key,
        args.model,
        extract_system_prompt,
        tender_file_ids,
        user_text=(
            "Extract tender product requirements as strict JSON only. "
            "Follow the schema and operator normalization rules from system prompt. "
            "Do not output is_hard in this stage."
        ),
        tools=extract_tools or None,
        include=extract_include or None,
        json_mode=True,
    )
    write_debug_json(debug_dir, f"extract_requirements_{ts}.json", extraction_response)
    requirements_json = extract_output_json(extraction_response)

    requirements_json = sanitize_requirements_payload(requirements_json)
    requirements_json = validate_requirements_payload(requirements_json)

    print("Reviewing hard/soft constraint flags from uploaded files...")
    review_prompt = (ReviewHardnessSig.__doc__ or "").strip()
    review_sections = [review_prompt]
    review_system_prompt = "\n\n".join(section for section in review_sections if section)
    review_tools: list[dict] = []
    review_include: list[str] = []
    if kb_vector_store_id:
        review_tools.append(
            {
                "type": "file_search",
                "vector_store_ids": [kb_vector_store_id],
                "max_num_results": 8,
            }
        )
        review_include.append("file_search_call.results")
    if dspy_web_search:
        review_tools.append({"type": "web_search", "external_web_access": True})
        review_include.append("web_search_call.results")
    review_user_text = (
        "Review each extracted requirement and output hardness decisions only "
        "(product_reviews[].decisions[] with requirement_index, is_hard, confidence).\n\n"
        f"requirements_json:\n{json.dumps(requirements_json, ensure_ascii=False)}"
    )
    review_response = call_responses(
        args.base_url,
        api_key,
        args.model,
        review_system_prompt,
        tender_file_ids,
        user_text=review_user_text,
        tools=review_tools or None,
        include=review_include or None,
        json_mode=True,
    )
    write_debug_json(debug_dir, f"review_hardness_{ts}.json", review_response)
    hardness_review_json = extract_output_json(review_response)
    hardness_review_json = sanitize_hardness_review_payload(hardness_review_json)
    hardness_review_json = validate_hardness_review_payload(hardness_review_json)
    write_json(BASE_DIR / "hardness_review.json", hardness_review_json)

    requirements_json = merge_hardness_review_into_requirements(
        requirements_json,
        hardness_review_json,
    )
    requirements_json = sanitize_requirements_payload(requirements_json)
    requirements_json = validate_reviewed_requirements_payload(
        requirements_json,
        require_confidence=True,
    )

    schema_tables = [t.strip() for t in args.schema_tables.split(",") if t.strip()]
    print(f"Fetching schema metadata for tables: {', '.join(schema_tables)}")
    schema_metadata = fetch_schema_metadata(
        args.mysql_container,
        args.mysql_user,
        args.mysql_password,
        args.mysql_db,
        schema_tables,
    )
    schema_metadata = validate_schema_payload(schema_metadata)
    write_json(BASE_DIR / "schema.json", schema_metadata)

    if not args.skip_field_alignment:
        print("Aligning requirement fields to database schema with LLM...")
        align_prompt = (AlignRequirementsToSchemaSig.__doc__ or "").strip()
        align_sections = [align_prompt]
        align_sections.append(f"schema_json:\n{json.dumps(schema_metadata, ensure_ascii=False)}")
        if article_reference_context:
            align_sections.append(f"article_reference_context:\n{article_reference_context}")
        align_system_prompt = "\n\n".join(section for section in align_sections if section)

        align_tools: list[dict] = []
        align_include: list[str] = []
        if kb_vector_store_id:
            align_tools.append(
                {
                    "type": "file_search",
                    "vector_store_ids": [kb_vector_store_id],
                    "max_num_results": 8,
                }
            )
            align_include.append("file_search_call.results")
        if dspy_web_search:
            align_tools.append({"type": "web_search", "external_web_access": True})
            align_include.append("web_search_call.results")

        align_user_text = (
            "Align the requirement fields to schema semantics and output strict JSON only. "
            "Do not change operator/value/is_hard/source.\n\n"
            f"requirements_json:\n{json.dumps(requirements_json, ensure_ascii=False)}"
        )
        try:
            align_response = call_responses(
                args.base_url,
                api_key,
                args.model,
                align_system_prompt,
                tender_file_ids,
                user_text=align_user_text,
                tools=align_tools or None,
                include=align_include or None,
                json_mode=True,
            )
            write_debug_json(debug_dir, f"align_fields_{ts}.json", align_response)
            aligned_requirements = extract_output_json(align_response)
            aligned_requirements = validate_requirements_payload(aligned_requirements)
            requirements_json = merge_alignment_into_reviewed_requirements(
                requirements_json,
                aligned_requirements,
            )
            requirements_json = validate_reviewed_requirements_payload(
                requirements_json,
                require_confidence=True,
            )
            write_json(BASE_DIR / "requirements_aligned.json", requirements_json)
        except Exception as exc:
            print(
                f"Warning: LLM field-alignment failed, fallback to reviewed requirements: {exc}",
                file=sys.stderr,
            )

    write_json(BASE_DIR / "requirements.json", requirements_json)

    print("Building SQL queries from hard constraints only...")
    sql_payload = build_hard_only_sql_queries(requirements_json, schema_metadata)
    allowed_tables = {table["name"] for table in schema_metadata.get("tables", [])}
    sql_payload = validate_sql_queries_payload(sql_payload, allowed_tables=allowed_tables)
    write_json(BASE_DIR / "sql_queries.json", sql_payload)

    queries = sql_payload.get("queries") or []
    query_results: list[dict] = []
    for item in queries:
        sql = item.get("sql")
        product_key = item.get("product_key")
        if not sql:
            continue
        print(f"Executing SQL for {product_key or 'unknown'}...")
        output = run_mysql_query(
            args.mysql_container,
            args.mysql_user,
            args.mysql_password,
            args.mysql_db,
            sql,
        )
        rows = parse_mysql_tsv(output)
        query_results.append(
            {
                "product_key": product_key,
                "sql": sql,
                "rows": rows,
            }
        )
    write_json(BASE_DIR / "sql_results.json", {"results": query_results})

    print("Selecting best candidate from SQL candidate set by soft constraints...")
    response = build_match_from_candidates(requirements_json, query_results)
    response = validate_prompt_result_payload(response)
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
        prompt_result = extract_output_json(response)
        final_result = build_final_result(prompt_result)
        write_json(BASE_DIR / "prompt_result.json", final_result)
    except Exception:
        pass
    print(f"Saved response to {output_path}")
    return 0
