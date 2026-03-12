from __future__ import annotations

import json
import os

from .openai_client import load_json_with_repair


def configure_dspy(model: str, api_key: str):
    try:
        import dspy  # type: ignore
    except Exception as exc:
        raise RuntimeError("dspy-ai is not installed. Install it with: pip install dspy-ai") from exc
    if api_key:
        os.environ.setdefault("OPENAI_API_KEY", api_key)
    lm = dspy.LM(model=model, model_type="responses")
    dspy.settings.configure(lm=lm)
    return dspy


def run_dspy_generate_sql(
    model: str,
    api_key: str,
    requirements_json: dict,
    schema_json: dict,
    web_context: str = "",
) -> dict:
    configure_dspy(model, api_key)
    from dspy_program import GenerateSQLModule

    program = GenerateSQLModule()
    prediction = program(
        requirements_json=json.dumps(requirements_json, ensure_ascii=False),
        schema_json=json.dumps(schema_json, ensure_ascii=False),
        web_context=web_context,
    )
    return load_json_with_repair(prediction.sql_queries_json, "sql_queries_json")


def run_dspy_extract_requirements(
    model: str,
    api_key: str,
    tender_text: str,
    web_context: str = "",
    article_reference_context: str = "",
) -> dict:
    configure_dspy(model, api_key)
    from dspy_program import ExtractRequirementsModule

    program = ExtractRequirementsModule()
    prediction = program(
        tender_text=tender_text,
        web_context=web_context,
        article_reference_context=article_reference_context,
    )
    return load_json_with_repair(prediction.requirements_json, "requirements_json")


def run_dspy_review_hardness(
    model: str,
    api_key: str,
    tender_text: str,
    requirements_json: dict,
    web_context: str = "",
) -> dict:
    configure_dspy(model, api_key)
    from dspy_program import ReviewHardnessModule

    program = ReviewHardnessModule()
    prediction = program(
        tender_text=tender_text,
        requirements_json=json.dumps(requirements_json, ensure_ascii=False),
        web_context=web_context,
    )
    return load_json_with_repair(prediction.reviewed_hardness_json, "reviewed_hardness_json")


def run_dspy_format_match(
    model: str,
    api_key: str,
    requirements_json: dict,
    schema_json: dict,
    sql_results: list[dict],
    web_context: str = "",
) -> dict:
    configure_dspy(model, api_key)
    from dspy_program import FormatMatchModule

    program = FormatMatchModule()
    prediction = program(
        requirements_json=json.dumps(requirements_json, ensure_ascii=False),
        schema_json=json.dumps(schema_json, ensure_ascii=False),
        sql_results_json=json.dumps(sql_results, ensure_ascii=False),
        web_context=web_context,
    )
    return load_json_with_repair(prediction.prompt_result_json, "prompt_result_json")
