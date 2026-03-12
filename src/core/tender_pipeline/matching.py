from __future__ import annotations

from .requirements_utils import to_float, to_range_pair


def eval_requirement_match(requirement: dict, row: dict) -> tuple[bool, bool]:
    field = requirement.get("field")
    operator = requirement.get("operator")
    value = requirement.get("value")
    if not isinstance(field, str) or not isinstance(operator, str):
        return False, False

    row_field_map = {
        "manufacturer": "manufacturer_name",
        "model": "product_name",
        "model_name": "product_name",
        "article_number": "article_number",
        "power_w": "electrical_power_w",
        "lumen_lm": "lumen_output_max",
        "lumen": "lumen_output_max",
        "cct": "color_temp_k_max",
        "cct_k": "color_temp_k_max",
        "cri": "cri",
        "ugr": "ugr",
        "lifetime_h": "runtime_hours",
        "life_hours": "runtime_hours",
        "runtime_hours": "runtime_hours",
        "ip_rating": "ip_rating",
        "ik_rating": "ik_rating",
    }

    if field in {"ambient_temp_range", "ambient_temperature"}:
        low, high = to_range_pair(value)
        min_temp = to_float(row.get("min_temp_c"))
        max_temp = to_float(row.get("max_temp_c"))
        checks = []
        if low is not None:
            if min_temp is None:
                return False, False
            checks.append(min_temp <= low)
        if high is not None:
            if max_temp is None:
                return False, False
            checks.append(max_temp >= high)
        if not checks:
            return False, False
        return all(checks), True

    if field == "control":
        text = str(value or "").lower()
        if "dali" not in text:
            return False, False
        dali_val = row.get("controls_dali")
        return str(dali_val).strip() in {"1", "true", "True"}, True

    row_key = row_field_map.get(field)
    if not row_key:
        return False, False
    row_val = row.get(row_key)
    if row_val is None:
        return False, False

    if operator in {"bool_true", "bool_false"}:
        expected = "1" if operator == "bool_true" else "0"
        return str(row_val).strip() == expected, True

    left_num = to_float(row_val)
    if operator in {"eq", "gte", "lte", "gt", "lt", "between", "in"} and left_num is not None:
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                return False, False
            low = to_float(value[0])
            high = to_float(value[1])
            if low is None or high is None:
                return False, False
            return low <= left_num <= high, True
        if operator == "in":
            if not isinstance(value, list):
                return False, False
            nums = [v for v in (to_float(v) for v in value) if v is not None]
            if not nums:
                return False, False
            return any(abs(left_num - n) < 1e-6 for n in nums), True
        right_num = to_float(value)
        if right_num is None:
            return False, False
        if operator == "eq":
            return abs(left_num - right_num) < 1e-6, True
        if operator == "gte":
            return left_num >= right_num, True
        if operator == "lte":
            return left_num <= right_num, True
        if operator == "gt":
            return left_num > right_num, True
        if operator == "lt":
            return left_num < right_num, True
        return False, False

    left_text = str(row_val).strip().lower()
    if operator == "contains":
        target = str(value or "").strip().lower()
        if not target:
            return False, False
        return target in left_text, True
    if operator == "in" and isinstance(value, list):
        targets = [str(v).strip().lower() for v in value if str(v).strip()]
        if not targets:
            return False, False
        return left_text in targets, True
    if operator == "eq":
        target = str(value or "").strip().lower()
        if not target:
            return False, False
        return left_text == target, True
    return False, False


def build_match_from_candidates(requirements_json: dict, query_results: list[dict]) -> dict:
    query_map = {
        item.get("product_key"): item.get("rows") or []
        for item in query_results
        if isinstance(item, dict)
    }
    uncertainties = list(requirements_json.get("uncertainties", []))
    match_results = []

    for product in requirements_json.get("tender_products", []):
        product_key = product.get("product_key")
        requirements = product.get("requirements") or []
        rows = query_map.get(product_key, [])

        if not rows:
            uncertainties.append(
                f"SQL returned 0 rows for product_key {product_key} under hard constraints."
            )
            match_results.append(
                {
                    "product_key": product_key,
                    "candidates": [
                        {
                            "db_product_id": None,
                            "db_product_name": None,
                            "passes_hard": False,
                            "matched_requirements": "",
                            "unmet_requirements": "No candidate rows returned from SQL hard-constraint filtering.",
                            "parameters": [],
                        }
                    ],
                }
            )
            continue

        scored_rows = []
        for row in rows:
            hard_total = hard_matched = soft_total = soft_matched = 0
            unmet_hard: list[str] = []
            unmet_soft: list[str] = []
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    continue
                matched, measurable = eval_requirement_match(requirement, row)
                if not measurable:
                    continue
                field_name = str(requirement.get("field") or "unknown")
                is_hard = bool(requirement.get("is_hard", False))
                if is_hard:
                    hard_total += 1
                    if matched:
                        hard_matched += 1
                    else:
                        unmet_hard.append(field_name)
                else:
                    soft_total += 1
                    if matched:
                        soft_matched += 1
                    else:
                        unmet_soft.append(field_name)
            passes_hard = hard_total == 0 or hard_matched == hard_total
            scored_rows.append(
                {
                    "row": row,
                    "passes_hard": passes_hard,
                    "hard_total": hard_total,
                    "hard_matched": hard_matched,
                    "soft_total": soft_total,
                    "soft_matched": soft_matched,
                    "unmet_hard": unmet_hard,
                    "unmet_soft": unmet_soft,
                }
            )

        scored_rows.sort(
            key=lambda item: (
                1 if item["passes_hard"] else 0,
                item["soft_matched"],
                -len(item["unmet_soft"]),
                item["hard_matched"],
            ),
            reverse=True,
        )
        best = scored_rows[0]
        row = best["row"]

        matched_text = (
            f"Hard matched {best['hard_matched']}/{best['hard_total']}; "
            f"soft matched {best['soft_matched']}/{best['soft_total']}."
        )
        unmet_parts = []
        if best["unmet_hard"]:
            unmet_parts.append("Hard unmet: " + ", ".join(best["unmet_hard"]))
        if best["unmet_soft"]:
            unmet_parts.append("Soft unmet: " + ", ".join(best["unmet_soft"]))
        unmet_text = "; ".join(unmet_parts)

        parameter_fields = [
            "article_number",
            "manufacturer_name",
            "product_name",
            "ugr",
            "cri",
            "ip_rating",
            "ik_rating",
            "min_temp_c",
            "max_temp_c",
            "electrical_power_w",
            "lumen_output_max",
            "color_temp_k_max",
            "runtime_hours",
            "controls_dali",
            "icon_tags",
        ]
        parameters = [
            {
                "field": name,
                "value": row.get(name),
                "unit": None,
                "db_field": name,
            }
            for name in parameter_fields
            if name in row
        ]

        match_results.append(
            {
                "product_key": product_key,
                "candidates": [
                    {
                        "db_product_id": row.get("product_id"),
                        "db_product_name": row.get("product_name"),
                        "passes_hard": best["passes_hard"],
                        "matched_requirements": matched_text,
                        "unmet_requirements": unmet_text,
                        "parameters": parameters,
                    }
                ],
            }
        )

    return {
        "tender_products": requirements_json.get("tender_products", []),
        "match_results": match_results,
        "uncertainties": uncertainties,
    }

