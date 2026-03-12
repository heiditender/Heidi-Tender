from __future__ import annotations

from copy import deepcopy
import json
import re

ALLOWED_OPERATORS = {
    "eq",
    "gte",
    "lte",
    "gt",
    "lt",
    "between",
    "in",
    "contains",
    "bool_true",
    "bool_false",
}

OPERATOR_ALIASES = {
    "=": "eq",
    "==": "eq",
    "equal": "eq",
    "equals": "eq",
    ">=": "gte",
    "greater or equal": "gte",
    "greater than or equal": "gte",
    "larger or equal": "gte",
    "<=": "lte",
    "lower or equal": "lte",
    "less or equal": "lte",
    "less than or equal": "lte",
    ">": "gt",
    "greater": "gt",
    "greater than": "gt",
    "<": "lt",
    "lower": "lt",
    "less": "lt",
    "true": "bool_true",
    "false": "bool_false",
}


def _normalized_uncertainties(raw_uncertainties) -> list[str]:
    normalized: list[str] = []
    if isinstance(raw_uncertainties, list):
        for item in raw_uncertainties:
            if isinstance(item, str):
                item = item.strip()
                if item:
                    normalized.append(item)
            else:
                normalized.append(json.dumps(item, ensure_ascii=False))
    elif raw_uncertainties is not None:
        normalized.append(str(raw_uncertainties))
    return normalized


def _normalize_operator(operator_value: object) -> str | None:
    if not isinstance(operator_value, str):
        return None
    normalized = re.sub(r"\s+", " ", operator_value.strip().lower())
    normalized = OPERATOR_ALIASES.get(normalized, normalized)
    if normalized not in ALLOWED_OPERATORS:
        return None
    return normalized


def _normalize_product_key(raw_key: object, idx: int) -> str:
    if isinstance(raw_key, str):
        key = raw_key.strip()
        if key:
            return key
    return f"item_{idx + 1:03d}"


def sanitize_requirements_payload(payload: dict) -> dict:
    normalized_uncertainties = _normalized_uncertainties(payload.get("uncertainties"))
    tender_products = payload.get("tender_products")
    duplicate_key_count = 0
    invalid_operator_count = 0
    missing_key_count = 0
    key_seen: dict[str, int] = {}

    if isinstance(tender_products, list):
        for idx, product in enumerate(tender_products):
            if not isinstance(product, dict):
                continue
            base_key = _normalize_product_key(product.get("product_key"), idx)
            if base_key.startswith("item_") and product.get("product_key") != base_key:
                missing_key_count += 1
            ordinal = key_seen.get(base_key, 0) + 1
            key_seen[base_key] = ordinal
            if ordinal > 1:
                duplicate_key_count += 1
                product_key = f"{base_key}__{ordinal:02d}"
            else:
                product_key = base_key
            product["product_key"] = product_key

            requirements = product.get("requirements")
            if not isinstance(requirements, list):
                product["requirements"] = []
                continue
            cleaned_requirements: list[dict] = []
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    continue
                normalized_operator = _normalize_operator(requirement.get("operator"))
                if normalized_operator is None:
                    invalid_operator_count += 1
                    field_name = requirement.get("field")
                    normalized_uncertainties.append(
                        f"Dropped requirement from {product_key} due to invalid operator: "
                        f"field={field_name!r}, operator={requirement.get('operator')!r}"
                    )
                    continue
                requirement["operator"] = normalized_operator
                cleaned_requirements.append(requirement)
            product["requirements"] = cleaned_requirements

    if missing_key_count:
        normalized_uncertainties.append(
            f"Generated default product_key for {missing_key_count} products with missing/invalid key."
        )
    if duplicate_key_count:
        normalized_uncertainties.append(
            f"Normalized {duplicate_key_count} duplicate product_key values by suffixing __NN."
        )
    if invalid_operator_count:
        normalized_uncertainties.append(
            f"Dropped {invalid_operator_count} requirements due to invalid operators."
        )
    payload["uncertainties"] = normalized_uncertainties
    return payload


def sanitize_hardness_review_payload(payload: dict) -> dict:
    payload["uncertainties"] = _normalized_uncertainties(payload.get("uncertainties"))
    product_reviews = payload.get("product_reviews")
    if not isinstance(product_reviews, list):
        payload["product_reviews"] = []
    return payload


def merge_hardness_review_into_requirements(
    requirements_payload: dict,
    review_payload: dict,
) -> dict:
    merged = deepcopy(requirements_payload)

    tender_products = merged.get("tender_products")
    if not isinstance(tender_products, list):
        tender_products = []
        merged["tender_products"] = tender_products

    merged_uncertainties = merged.get("uncertainties")
    normalized_uncertainties: list[str] = []
    if isinstance(merged_uncertainties, list):
        for item in merged_uncertainties:
            normalized_uncertainties.append(item if isinstance(item, str) else str(item))
    elif merged_uncertainties is not None:
        normalized_uncertainties.append(str(merged_uncertainties))

    review_uncertainties = review_payload.get("uncertainties")
    if isinstance(review_uncertainties, list):
        for item in review_uncertainties:
            normalized_uncertainties.append(item if isinstance(item, str) else str(item))
    elif review_uncertainties is not None:
        normalized_uncertainties.append(str(review_uncertainties))

    product_map: dict[str, list] = {}
    for product in tender_products:
        if not isinstance(product, dict):
            continue
        key = product.get("product_key")
        if not isinstance(key, str) or not key.strip():
            continue
        requirements = product.get("requirements")
        if not isinstance(requirements, list):
            requirements = []
            product["requirements"] = requirements
        product_map[key] = requirements

    applied_keys: set[tuple[str, int]] = set()
    duplicate_decisions = 0
    unknown_products = 0
    out_of_range = 0

    product_reviews = review_payload.get("product_reviews")
    if isinstance(product_reviews, list):
        for product_review in product_reviews:
            if not isinstance(product_review, dict):
                continue
            product_key = product_review.get("product_key")
            if not isinstance(product_key, str) or not product_key.strip():
                continue
            requirements = product_map.get(product_key)
            if requirements is None:
                unknown_products += 1
                continue
            decisions = product_review.get("decisions")
            if not isinstance(decisions, list):
                continue
            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                raw_idx = decision.get("requirement_index")
                if not isinstance(raw_idx, int):
                    continue
                if raw_idx < 0 or raw_idx >= len(requirements):
                    out_of_range += 1
                    continue
                decision_key = (product_key, raw_idx)
                if decision_key in applied_keys:
                    duplicate_decisions += 1
                applied_keys.add(decision_key)

                requirement = requirements[raw_idx]
                if not isinstance(requirement, dict):
                    out_of_range += 1
                    continue
                requirement["is_hard"] = bool(decision.get("is_hard"))
                confidence = decision.get("confidence")
                if isinstance(confidence, (int, float)):
                    requirement["hardness_confidence"] = float(confidence)

    missing_decisions = 0
    for product in tender_products:
        if not isinstance(product, dict):
            continue
        product_key = product.get("product_key")
        if not isinstance(product_key, str):
            product_key = ""
        requirements = product.get("requirements")
        if not isinstance(requirements, list):
            continue
        for idx, requirement in enumerate(requirements):
            if not isinstance(requirement, dict):
                continue
            if (product_key, idx) not in applied_keys:
                if requirement.get("is_hard") is None:
                    requirement["is_hard"] = False
                    requirement["hardness_confidence"] = 0.0
                missing_decisions += 1
            elif (
                requirement.get("is_hard") is not None
                and "hardness_confidence" not in requirement
            ):
                requirement["hardness_confidence"] = 0.0

    if missing_decisions:
        normalized_uncertainties.append(
            f"Hardness review missing {missing_decisions} requirement decisions; defaulted to is_hard=false."
        )
    if unknown_products:
        normalized_uncertainties.append(
            f"Hardness review referenced {unknown_products} unknown product_key entries."
        )
    if out_of_range:
        normalized_uncertainties.append(
            f"Hardness review had {out_of_range} out-of-range requirement_index entries."
        )
    if duplicate_decisions:
        normalized_uncertainties.append(
            f"Hardness review contained {duplicate_decisions} duplicate decisions; last one applied."
        )

    merged["uncertainties"] = normalized_uncertainties
    return merged


def merge_alignment_into_reviewed_requirements(
    reviewed_payload: dict,
    aligned_payload: dict,
) -> dict:
    merged = deepcopy(reviewed_payload)
    normalized_uncertainties = _normalized_uncertainties(merged.get("uncertainties"))
    normalized_uncertainties.extend(_normalized_uncertainties(aligned_payload.get("uncertainties")))

    tender_products = merged.get("tender_products")
    if not isinstance(tender_products, list):
        merged["tender_products"] = []
        merged["uncertainties"] = normalized_uncertainties
        return merged

    aligned_products = aligned_payload.get("tender_products")
    aligned_map: dict[str, dict] = {}
    if isinstance(aligned_products, list):
        for product in aligned_products:
            if not isinstance(product, dict):
                continue
            product_key = product.get("product_key")
            if not isinstance(product_key, str):
                continue
            if product_key not in aligned_map:
                aligned_map[product_key] = product

    missing_products = 0
    req_len_mismatch = 0
    updated_fields = 0
    updated_units = 0

    for product in tender_products:
        if not isinstance(product, dict):
            continue
        product_key = product.get("product_key")
        if not isinstance(product_key, str):
            continue
        aligned_product = aligned_map.get(product_key)
        if aligned_product is None:
            missing_products += 1
            continue

        base_requirements = product.get("requirements")
        aligned_requirements = aligned_product.get("requirements")
        if not isinstance(base_requirements, list):
            continue
        if not isinstance(aligned_requirements, list):
            req_len_mismatch += 1
            continue
        if len(base_requirements) != len(aligned_requirements):
            req_len_mismatch += 1

        for idx, base_req in enumerate(base_requirements):
            if not isinstance(base_req, dict):
                continue
            if idx >= len(aligned_requirements):
                break
            aligned_req = aligned_requirements[idx]
            if not isinstance(aligned_req, dict):
                continue

            aligned_field = aligned_req.get("field")
            if isinstance(aligned_field, str) and aligned_field.strip():
                aligned_field = aligned_field.strip()
                if aligned_field != base_req.get("field"):
                    base_req["field"] = aligned_field
                    updated_fields += 1

            if "unit" in aligned_req:
                aligned_unit = aligned_req.get("unit")
                if aligned_unit is None:
                    if base_req.get("unit") is not None:
                        base_req["unit"] = None
                        updated_units += 1
                elif isinstance(aligned_unit, str):
                    clean_unit = aligned_unit.strip() or None
                    if clean_unit != base_req.get("unit"):
                        base_req["unit"] = clean_unit
                        updated_units += 1

    if missing_products:
        normalized_uncertainties.append(
            f"Alignment response missing {missing_products} product_key entries; kept original fields."
        )
    if req_len_mismatch:
        normalized_uncertainties.append(
            f"Alignment response had requirement length mismatch in {req_len_mismatch} products; merged by index where possible."
        )
    if updated_fields or updated_units:
        normalized_uncertainties.append(
            f"Applied field-alignment updates: fields={updated_fields}, units={updated_units}."
        )

    merged["uncertainties"] = normalized_uncertainties
    return merged


def to_float(value):
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


def to_range_pair(value):
    if isinstance(value, list) and len(value) == 2:
        return to_float(value[0]), to_float(value[1])
    if isinstance(value, str):
        numbers = re.findall(r"-?\d+(?:[.,]\d+)?", value)
        if len(numbers) >= 2:
            return to_float(numbers[0]), to_float(numbers[1])
    return None, None


def sql_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"
