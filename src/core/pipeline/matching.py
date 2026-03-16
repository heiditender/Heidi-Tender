from __future__ import annotations

import re
from typing import Any


NUMERIC_OPERATORS = {"eq", "gte", "lte", "gt", "lt", "between", "in"}
STRING_OPERATORS = {"eq", "contains", "in"}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def _is_unknown_numeric(value: float) -> bool:
    return abs(value) < 1e-12


def _split_field(field: str) -> str:
    return field.split(".", 1)[1] if "." in field else field


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _stable_row_key(row: dict[str, Any]) -> tuple[tuple[int, float | str, str], str]:
    product_id_raw = row.get("product_id")
    product_id_text = _safe_text(product_id_raw)
    product_id_num = _to_float(product_id_raw)
    if product_id_num is not None:
        product_id_key: tuple[int, float | str, str] = (0, product_id_num, product_id_text)
    else:
        product_id_key = (1, product_id_text, product_id_text)
    product_name = _safe_text(row.get("product_name")).lower()
    return product_id_key, product_name


def _is_numeric_requirement(requirement: dict) -> bool:
    operator = requirement.get("operator")
    value = requirement.get("value")
    if not isinstance(operator, str) or operator not in NUMERIC_OPERATORS:
        return False
    if operator == "between":
        return (
            isinstance(value, list)
            and len(value) == 2
            and _to_float(value[0]) is not None
            and _to_float(value[1]) is not None
        )
    if operator == "in":
        return isinstance(value, list) and any(_to_float(item) is not None for item in value)
    return _to_float(value) is not None


def _is_string_requirement(requirement: dict) -> bool:
    operator = requirement.get("operator")
    value = requirement.get("value")
    if not isinstance(operator, str) or operator not in STRING_OPERATORS:
        return False
    if operator == "contains":
        return bool(_safe_text(value))
    if operator == "eq":
        return bool(_safe_text(value))
    if operator == "in":
        return isinstance(value, list) and any(_safe_text(item) for item in value)
    return False


def _top_k_for_count(count: int) -> int:
    if count <= 10:
        return count
    if count <= 100:
        return 15
    if count <= 1000:
        return 20
    return 30


def _numeric_score_for_requirement(requirement: dict, row: dict[str, Any]) -> dict | None:
    field = requirement.get("field")
    operator = requirement.get("operator")
    raw_value = requirement.get("value")
    if not isinstance(field, str) or not isinstance(operator, str) or operator not in NUMERIC_OPERATORS:
        return None

    column_name = _split_field(field)
    row_value = row.get(column_name)
    actual = _to_float(row_value)
    if actual is None or _is_unknown_numeric(actual):
        return None

    matched = False
    score = 0.0
    required_value: float | list[float] | None

    if operator == "between":
        if not isinstance(raw_value, list) or len(raw_value) != 2:
            return None
        low = _to_float(raw_value[0])
        high = _to_float(raw_value[1])
        if low is None or high is None:
            return None
        if low > high:
            low, high = high, low
        matched = low <= actual <= high
        if matched:
            score = 1.0
        else:
            distance = min(abs(actual - low), abs(actual - high))
            denominator = max(abs(high - low), abs(low), abs(high), 1.0)
            score = max(0.0, 1.0 - (distance / denominator))
        required_value = [low, high]
    elif operator == "in":
        if not isinstance(raw_value, list):
            return None
        candidates = [candidate for candidate in (_to_float(item) for item in raw_value) if candidate is not None]
        if not candidates:
            return None
        matched = any(abs(actual - candidate) < 1e-6 for candidate in candidates)
        score = max(
            max(0.0, 1.0 - (abs(actual - candidate) / max(abs(candidate), 1.0))) for candidate in candidates
        )
        required_value = candidates
    else:
        target = _to_float(raw_value)
        if target is None:
            return None
        denominator = max(abs(target), 1.0)
        required_value = target
        if operator == "eq":
            matched = abs(actual - target) < 1e-6
            score = max(0.0, 1.0 - (abs(actual - target) / denominator))
        elif operator == "gte":
            matched = actual >= target
            score = 1.0 if matched else max(0.0, 1.0 - ((target - actual) / denominator))
        elif operator == "gt":
            matched = actual > target
            score = 1.0 if matched else max(0.0, 1.0 - ((target - actual) / denominator))
        elif operator == "lte":
            matched = actual <= target
            score = 1.0 if matched else max(0.0, 1.0 - ((actual - target) / denominator))
        elif operator == "lt":
            matched = actual < target
            score = 1.0 if matched else max(0.0, 1.0 - ((actual - target) / denominator))
        else:  # pragma: no cover
            return None

    return {
        "field": field,
        "operator": operator,
        "required": required_value,
        "actual": actual,
        "score": round(score, 4),
        "matched": matched,
    }


def _string_match_for_requirement(requirement: dict, row: dict[str, Any]) -> dict | None:
    field = requirement.get("field")
    operator = requirement.get("operator")
    raw_value = requirement.get("value")
    if not isinstance(field, str) or not isinstance(operator, str) or operator not in STRING_OPERATORS:
        return None

    column_name = _split_field(field)
    row_value = row.get(column_name)
    if row_value is None:
        return None

    actual = _safe_text(row_value).lower()
    if not actual:
        return None

    matched = False
    required: str | list[str] | None

    if operator == "contains":
        target = _safe_text(raw_value).lower()
        if not target:
            return None
        matched = target in actual
        required = target
    elif operator == "eq":
        target = _safe_text(raw_value).lower()
        if not target:
            return None
        matched = actual == target
        required = target
    elif operator == "in":
        if not isinstance(raw_value, list):
            return None
        targets = [text for text in (_safe_text(item).lower() for item in raw_value) if text]
        if not targets:
            return None
        matched = actual in targets
        required = targets
    else:  # pragma: no cover
        return None

    return {
        "field": field,
        "operator": operator,
        "required": required,
        "actual": _safe_text(row_value),
        "matched": matched,
    }


def _build_string_field_values(
    string_requirements: list[dict[str, Any]],
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for requirement in string_requirements:
        field = requirement.get("field")
        operator = requirement.get("operator")
        if not isinstance(field, str) or not isinstance(operator, str):
            continue
        if field in seen:
            continue
        seen.add(field)
        column_name = _split_field(field)
        values.append(
            {
                "field": field,
                "operator": operator,
                "expected": requirement.get("value"),
                "actual": row.get(column_name),
            }
        )
    return values


def _build_numeric_constraints_summary(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for requirement in requirements:
        summary.append(
            {
                "field": requirement.get("field"),
                "operator": requirement.get("operator"),
                "required": requirement.get("value"),
                "unit": requirement.get("unit"),
            }
        )
    return summary


def _build_string_constraints_summary(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for requirement in requirements:
        summary.append(
            {
                "field": requirement.get("field"),
                "operator": requirement.get("operator"),
                "required": requirement.get("value"),
            }
        )
    return summary


def _score_row_numeric(
    numeric_requirements: list[dict[str, Any]],
    string_requirements: list[dict[str, Any]],
    row: dict[str, Any],
) -> dict[str, Any]:
    details = [detail for detail in (_numeric_score_for_requirement(requirement, row) for requirement in numeric_requirements) if detail]
    comparable_count = len(details)
    score = sum(detail["score"] for detail in details) / comparable_count if comparable_count else 0.0
    matched = [detail["field"] for detail in details if detail["matched"]]
    unmet = [detail["field"] for detail in details if not detail["matched"]]
    return {
        "row": row,
        "mode": "numeric",
        "pre_rank_score": round(score, 4),
        "comparable_count": comparable_count,
        "matched_fields": matched,
        "unmet_fields": unmet,
        "numeric_details": details,
        "string_matches": [],
        "string_field_values": _build_string_field_values(string_requirements, row),
    }


def _score_row_string(
    string_requirements: list[dict[str, Any]],
    row: dict[str, Any],
) -> dict[str, Any]:
    details = [detail for detail in (_string_match_for_requirement(requirement, row) for requirement in string_requirements) if detail]
    comparable_count = len(details)
    matched_count = sum(1 for detail in details if detail["matched"])
    score = matched_count / comparable_count if comparable_count else 0.0
    matched = [detail["field"] for detail in details if detail["matched"]]
    unmet = [detail["field"] for detail in details if not detail["matched"]]
    return {
        "row": row,
        "mode": "string_fallback",
        "pre_rank_score": round(score, 4),
        "comparable_count": comparable_count,
        "matched_fields": matched,
        "unmet_fields": unmet,
        "numeric_details": [],
        "string_matches": details,
        "string_field_values": _build_string_field_values(string_requirements, row),
    }


def _candidate_sort_key(scored_row: dict[str, Any]) -> tuple[float, int, tuple[int, float | str, str], str]:
    product_id, product_name = _stable_row_key(scored_row.get("row") or {})
    return (
        -float(scored_row.get("pre_rank_score") or 0.0),
        -int(scored_row.get("comparable_count") or 0),
        product_id,
        product_name,
    )


def _build_llm_candidate_summary(
    scored_row: dict[str, Any],
    *,
    pre_rank: int,
) -> dict[str, Any]:
    row = scored_row["row"]
    return {
        "pre_rank": pre_rank,
        "db_product_id": row.get("product_id"),
        "db_product_name": row.get("product_name"),
        "pre_rank_score": round(float(scored_row.get("pre_rank_score") or 0.0), 4),
        "pre_rank_mode": scored_row.get("mode"),
        "comparable_numeric_count": len(scored_row.get("numeric_details") or []),
        "comparable_string_count": len(scored_row.get("string_matches") or []),
        "numeric_field_details": scored_row.get("numeric_details") or [],
        "string_field_values": scored_row.get("string_field_values") or [],
    }


def _build_deterministic_candidate(
    scored_row: dict[str, Any],
    *,
    rank: int,
) -> dict[str, Any]:
    row = scored_row["row"]
    matched_fields = list(scored_row.get("matched_fields") or [])
    unmet_fields = list(scored_row.get("unmet_fields") or [])
    comparable_count = int(scored_row.get("comparable_count") or 0)
    mode = str(scored_row.get("mode") or "numeric")
    score = round(float(scored_row.get("pre_rank_score") or 0.0), 4)
    if mode == "numeric":
        explanation = (
            f"Deterministic pre-rank: numeric soft score {score:.4f} "
            f"across {comparable_count} comparable numeric constraints."
        )
    else:
        explanation = (
            f"Deterministic pre-rank: string fallback score {score:.4f} "
            f"across {comparable_count} comparable string constraints."
        )
    if comparable_count == 0:
        explanation = "Deterministic pre-rank: no comparable soft constraints were available."
    return {
        "rank": rank,
        "db_product_id": row.get("product_id"),
        "db_product_name": row.get("product_name"),
        "passes_hard": True,
        "soft_match_score": score,
        "matched_soft_constraints": matched_fields,
        "unmet_soft_constraints": unmet_fields,
        "explanation": explanation,
    }


def build_step7_prerank_bundle(step4_data: dict, step6_data: dict) -> dict:
    result_map = {
        item.get("product_key"): item.get("rows") or []
        for item in step6_data.get("results", [])
        if isinstance(item, dict)
    }

    llm_products: list[dict[str, Any]] = []
    match_results: list[dict[str, Any]] = []
    product_summaries: list[dict[str, Any]] = []
    total_candidates_before = 0
    total_candidates_after = 0
    products_truncated = 0
    numeric_mode_products = 0
    string_fallback_products = 0

    for product in step4_data.get("tender_products", []):
        if not isinstance(product, dict):
            continue
        product_key = product.get("product_key")
        if not isinstance(product_key, str):
            continue

        soft_requirements = [
            requirement
            for requirement in (product.get("requirements") or [])
            if isinstance(requirement, dict)
            and requirement.get("is_hard") is not True
            and isinstance(requirement.get("operator"), str)
        ]
        numeric_requirements = [requirement for requirement in soft_requirements if _is_numeric_requirement(requirement)]
        string_requirements = [requirement for requirement in soft_requirements if _is_string_requirement(requirement)]
        rows = [row for row in result_map.get(product_key, []) if isinstance(row, dict)]

        total_candidates_before += len(rows)
        top_k = _top_k_for_count(len(rows))
        if len(rows) > top_k:
            products_truncated += 1

        mode = "numeric" if numeric_requirements else "string_fallback"
        if mode == "numeric":
            numeric_mode_products += 1
            scored_rows = [
                _score_row_numeric(numeric_requirements, string_requirements, row)
                for row in rows
            ]
        else:
            string_fallback_products += 1
            scored_rows = [_score_row_string(string_requirements, row) for row in rows]

        scored_rows.sort(key=_candidate_sort_key)
        shortlisted = scored_rows[:top_k]
        total_candidates_after += len(shortlisted)

        llm_products.append(
            {
                "product_key": product_key,
                "product_name": product.get("product_name"),
                "pre_rank_mode": mode,
                "candidate_count_before": len(rows),
                "candidate_count_after": len(shortlisted),
                "numeric_soft_constraints": _build_numeric_constraints_summary(numeric_requirements),
                "string_soft_constraints": _build_string_constraints_summary(string_requirements),
                "shortlisted_candidates": [
                    _build_llm_candidate_summary(scored_row, pre_rank=index)
                    for index, scored_row in enumerate(shortlisted, start=1)
                ],
            }
        )

        match_results.append(
            {
                "product_key": product_key,
                "candidates": [
                    _build_deterministic_candidate(scored_row, rank=index)
                    for index, scored_row in enumerate(shortlisted, start=1)
                ],
            }
        )

        product_summaries.append(
            {
                "product_key": product_key,
                "mode": mode,
                "comparable_numeric_count": len(numeric_requirements),
                "comparable_string_count": len(string_requirements),
                "candidate_count_before": len(rows),
                "candidate_count_after": len(shortlisted),
            }
        )

    pre_rank_summary = {
        "total_candidates_before": total_candidates_before,
        "total_candidates_after": total_candidates_after,
        "products_truncated": products_truncated,
        "numeric_mode_products": numeric_mode_products,
        "string_fallback_products": string_fallback_products,
        "product_summaries": product_summaries,
    }

    return {
        "llm_input": {"products": llm_products},
        "fallback_payload": {
            "match_results": match_results,
            "pre_rank_summary": pre_rank_summary,
        },
        "pre_rank_summary": pre_rank_summary,
    }


def build_fallback_step7(step4_data: dict, step6_data: dict) -> dict:
    return build_step7_prerank_bundle(step4_data, step6_data)["fallback_payload"]
