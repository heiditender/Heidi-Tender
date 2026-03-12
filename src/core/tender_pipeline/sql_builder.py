from __future__ import annotations

from .requirements_utils import sql_quote, to_float, to_range_pair


def schema_column_map(schema_metadata: dict) -> dict[str, set[str]]:
    table_map: dict[str, set[str]] = {}
    for table in schema_metadata.get("tables", []):
        name = table.get("name")
        if not isinstance(name, str):
            continue
        cols = {
            col.get("name")
            for col in table.get("columns", [])
            if isinstance(col, dict) and isinstance(col.get("name"), str)
        }
        table_map[name] = cols
    return table_map


def build_hard_only_condition(requirement: dict, schema_map: dict[str, set[str]]) -> str | None:
    field = requirement.get("field")
    operator = requirement.get("operator")
    value = requirement.get("value")
    if not isinstance(field, str) or not isinstance(operator, str):
        return None

    field_map = {
        "manufacturer": ("match_products", "manufacturer_name", "text"),
        "model": ("match_products", "product_name", "text"),
        "model_name": ("match_products", "product_name", "text"),
        "article_number": ("match_products", "article_number", "text"),
        "power_w": ("match_specs", "electrical_power_w", "number"),
        "lumen_lm": ("match_specs", "lumen_output_max", "number"),
        "lumen": ("match_specs", "lumen_output_max", "number"),
        "cct": ("match_specs", "color_temp_k_max", "number"),
        "cct_k": ("match_specs", "color_temp_k_max", "number"),
        "cri": ("match_specs", "cri", "number"),
        "ugr": ("match_specs", "ugr", "number"),
        "lifetime_h": ("match_specs", "runtime_hours", "number"),
        "life_hours": ("match_specs", "runtime_hours", "number"),
        "runtime_hours": ("match_specs", "runtime_hours", "number"),
        "ip_rating": ("match_specs", "ip_rating", "number"),
        "ik_rating": ("match_specs", "ik_rating", "number"),
    }

    if field in {"ambient_temp_range", "ambient_temperature"}:
        cols = schema_map.get("match_specs", set())
        if "min_temp_c" not in cols and "max_temp_c" not in cols:
            return None
        low, high = to_range_pair(value)
        pieces = []
        if low is not None and "min_temp_c" in cols:
            pieces.append(f"ms.min_temp_c <= {low:g}")
        if high is not None and "max_temp_c" in cols:
            pieces.append(f"ms.max_temp_c >= {high:g}")
        if not pieces:
            return None
        return " AND ".join(pieces)

    if field == "control":
        cols = schema_map.get("match_specs", set())
        val = str(value or "").lower()
        if "dali" in val and "controls_dali" in cols:
            return "ms.controls_dali = 1"
        return None

    mapping = field_map.get(field)
    if not mapping:
        return None

    table_name, column_name, value_type = mapping
    if column_name not in schema_map.get(table_name, set()):
        return None
    alias = "mp" if table_name == "match_products" else "ms"
    col = f"{alias}.{column_name}"

    op = operator
    if field in {"ip_rating", "ik_rating"} and op == "eq":
        op = "gte"

    if value_type == "number":
        if op == "between":
            if isinstance(value, list) and len(value) == 2:
                low = to_float(value[0])
                high = to_float(value[1])
                if low is not None and high is not None:
                    return f"{col} BETWEEN {low:g} AND {high:g}"
            return None
        if op == "in":
            if not isinstance(value, list):
                return None
            nums = [v for v in (to_float(v) for v in value) if v is not None]
            if not nums:
                return None
            return f"{col} IN ({', '.join(f'{n:g}' for n in nums)})"
        if op in {"bool_true", "bool_false"}:
            return f"{col} = {1 if op == 'bool_true' else 0}"
        num = to_float(value)
        if num is None:
            return None
        op_map = {"eq": "=", "gte": ">=", "lte": "<=", "gt": ">", "lt": "<"}
        sql_op = op_map.get(op)
        if not sql_op:
            return None
        return f"{col} {sql_op} {num:g}"

    if value_type == "text":
        if op == "contains":
            text = str(value or "").strip()
            if not text:
                return None
            safe_text = text.replace("%", "%%").replace("'", "''")
            return f"{col} LIKE '%{safe_text}%'"
        if op == "in":
            if not isinstance(value, list):
                return None
            vals = [str(v).strip() for v in value if str(v).strip()]
            if not vals:
                return None
            return f"{col} IN ({', '.join(sql_quote(v) for v in vals)})"
        if op in {"eq", "gte", "lte", "gt", "lt"}:
            text = str(value or "").strip()
            if not text:
                return None
            if op != "eq":
                return None
            return f"{col} = {sql_quote(text)}"
    return None


def build_hard_only_sql_queries(requirements_json: dict, schema_metadata: dict) -> dict:
    schema_map = schema_column_map(schema_metadata)
    select_candidates = [
        ("mp", "product_id"),
        ("mp", "article_number"),
        ("mp", "product_name"),
        ("mp", "manufacturer_name"),
        ("ms", "ugr"),
        ("ms", "cri"),
        ("ms", "ip_rating"),
        ("ms", "ik_rating"),
        ("ms", "min_temp_c"),
        ("ms", "max_temp_c"),
        ("ms", "electrical_power_w"),
        ("ms", "lumen_output_max"),
        ("ms", "color_temp_k_max"),
        ("ms", "runtime_hours"),
        ("ms", "controls_dali"),
        ("mc", "icon_tags"),
    ]

    select_exprs: list[str] = []
    for alias, col in select_candidates:
        table = (
            "match_products"
            if alias == "mp"
            else "match_specs"
            if alias == "ms"
            else "match_certs"
        )
        if col in schema_map.get(table, set()):
            select_exprs.append(f"{alias}.{col}")
    if not select_exprs:
        select_exprs = ["mp.product_id"]

    queries = []
    for product in requirements_json.get("tender_products", []):
        product_key = product.get("product_key")
        requirements = product.get("requirements") or []
        where_clauses: list[str] = []
        if "is_current" in schema_map.get("match_products", set()):
            where_clauses.append("mp.is_current = 1")
        if "is_current" in schema_map.get("match_specs", set()):
            where_clauses.append("ms.is_current = 1")

        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            if not requirement.get("is_hard", False):
                continue
            condition = build_hard_only_condition(requirement, schema_map)
            if condition:
                where_clauses.append(condition)
        if not where_clauses:
            where_clauses.append("1 = 1")

        sql = (
            "SELECT "
            + ", ".join(select_exprs)
            + " FROM match_products mp "
            + "JOIN match_specs ms ON mp.product_id = ms.product_id "
            + "LEFT JOIN match_certs mc ON mp.product_id = mc.product_id "
            + "WHERE "
            + " AND ".join(f"({c})" for c in where_clauses)
            + ";"
        )
        queries.append({"product_key": product_key, "sql": sql})

    return {"queries": queries}
