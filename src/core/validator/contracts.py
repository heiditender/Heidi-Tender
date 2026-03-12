import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

ALLOWED_REQUIREMENT_OPERATORS = {
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

_OPERATOR_ALIASES = {
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

_SQL_COMMENT_PATTERN = re.compile(r"(--|#|/\*|\*/)")
_SQL_FORBIDDEN_PATTERN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|create|truncate|replace|"
    r"grant|revoke|merge|call|do|handler|load|lock|unlock|set|use|"
    r"show|describe|desc|explain|analyze|optimize|repair|flush|kill"
    r")\b",
    re.IGNORECASE,
)
_SQL_FROM_OR_JOIN_PATTERN = re.compile(
    r"\b(?:from|join)\s+([`\"]?[a-zA-Z_][\w$]*[`\"]?(?:\.[`\"]?[a-zA-Z_][\w$]*[`\"]?)?)",
    re.IGNORECASE,
)


def _normalize_operator(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = _OPERATOR_ALIASES.get(normalized, normalized)
    if normalized not in ALLOWED_REQUIREMENT_OPERATORS:
        raise ValueError(
            f"unsupported operator '{value}'. "
            f"Allowed: {sorted(ALLOWED_REQUIREMENT_OPERATORS)}"
        )
    return normalized


def _normalize_table_name(raw_name: str) -> str:
    parts = [p.strip("`\"") for p in raw_name.split(".") if p]
    return parts[-1] if parts else raw_name.strip("`\"")


def _extract_table_names(sql: str) -> list[str]:
    names = []
    for match in _SQL_FROM_OR_JOIN_PATTERN.finditer(sql):
        names.append(_normalize_table_name(match.group(1)))
    return names


def validate_safe_select_sql(sql: str, allowed_tables: set[str] | None = None) -> str:
    if not isinstance(sql, str):
        raise ValueError("sql must be a string")
    statement = sql.strip()
    if not statement:
        raise ValueError("sql is empty")
    if _SQL_COMMENT_PATTERN.search(statement):
        raise ValueError("sql comments are not allowed")

    if statement.endswith(";"):
        statement = statement[:-1].strip()
    if ";" in statement:
        raise ValueError("multiple SQL statements are not allowed")
    if not re.match(r"(?is)^select\b", statement):
        raise ValueError("only SELECT statements are allowed")
    if re.search(r"(?is)\binto\s+(outfile|dumpfile)\b", statement):
        raise ValueError("SELECT ... INTO OUTFILE/DUMPFILE is not allowed")
    if _SQL_FORBIDDEN_PATTERN.search(statement):
        raise ValueError("forbidden SQL keyword detected")

    table_names = _extract_table_names(statement)
    if not table_names:
        raise ValueError("SQL must reference at least one table in FROM/JOIN")
    if allowed_tables is not None:
        unknown = sorted({name for name in table_names if name not in allowed_tables})
        if unknown:
            raise ValueError(
                f"SQL references tables outside allowlist: {', '.join(unknown)}"
            )
    return statement


class RequirementSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_name: str | None = None
    snippet: str | None = None


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    operator: str
    value: Any = None
    unit: str | None = None
    is_hard: bool | None = None
    hardness_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: RequirementSource | None = None

    @field_validator("operator", mode="before")
    @classmethod
    def validate_operator(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("operator must be a string")
        return _normalize_operator(value)


class TenderProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str = Field(min_length=1)
    product_name: str | None = None
    quantity: int | float | str | None = None
    requirements: list[Requirement] = Field(default_factory=list)


class RequirementsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tender_products: list[TenderProduct] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_product_keys(self):
        seen: set[str] = set()
        duplicates: set[str] = set()
        for product in self.tender_products:
            if product.product_key in seen:
                duplicates.add(product.product_key)
            seen.add(product.product_key)
        if duplicates:
            dup_text = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate product_key detected: {dup_text}")
        return self


class HardnessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_index: int = Field(ge=0)
    is_hard: bool
    confidence: float = Field(ge=0.0, le=1.0)


class HardnessProductReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str = Field(min_length=1)
    decisions: list[HardnessDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_requirement_indexes(self):
        seen: set[int] = set()
        duplicates: set[int] = set()
        for decision in self.decisions:
            if decision.requirement_index in seen:
                duplicates.add(decision.requirement_index)
            seen.add(decision.requirement_index)
        if duplicates:
            dup_text = ", ".join(str(v) for v in sorted(duplicates))
            raise ValueError(
                f"duplicate requirement_index in hardness decisions for product_key "
                f"'{self.product_key}': {dup_text}"
            )
        return self


class HardnessReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_reviews: list[HardnessProductReview] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_product_keys(self):
        seen: set[str] = set()
        duplicates: set[str] = set()
        for product_review in self.product_reviews:
            if product_review.product_key in seen:
                duplicates.add(product_review.product_key)
            seen.add(product_review.product_key)
        if duplicates:
            dup_text = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate product_key in hardness review: {dup_text}")
        return self


class SchemaColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str = Field(min_length=1)


class SchemaTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    columns: list[SchemaColumn] = Field(default_factory=list)


class SchemaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: list[SchemaTable] = Field(default_factory=list)


class SQLQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str = Field(min_length=1)
    sql: str

    @field_validator("sql", mode="before")
    @classmethod
    def validate_sql_shape(cls, value: Any) -> str:
        return validate_safe_select_sql(value)


class SQLQueriesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[SQLQuery] = Field(default_factory=list)


class MatchParameter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str | None = None
    value: Any = None
    unit: str | None = None
    db_field: str | None = None


class MatchCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    db_product_id: str | int | None = None
    db_product_name: str | None = None
    passes_hard: bool
    matched_requirements: str | None = None
    unmet_requirements: str | None = None
    parameters: list[MatchParameter] = Field(default_factory=list)


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str = Field(min_length=1)
    candidates: list[MatchCandidate] = Field(default_factory=list)


class PromptResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tender_products: list[TenderProduct] = Field(default_factory=list)
    match_results: list[MatchResult] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


def _validation_error_message(prefix: str, exc: ValidationError) -> str:
    details = []
    for issue in exc.errors():
        loc = ".".join(str(p) for p in issue.get("loc", ()))
        msg = issue.get("msg", "validation error")
        details.append(f"{loc}: {msg}")
    return f"{prefix}: {'; '.join(details)}"


def validate_requirements_payload(payload: dict) -> dict:
    try:
        parsed = RequirementsPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(_validation_error_message("requirements validation failed", exc)) from exc
    return parsed.model_dump(mode="python")


def validate_reviewed_requirements_payload(
    payload: dict,
    *,
    require_confidence: bool = True,
) -> dict:
    normalized = validate_requirements_payload(payload)
    violations: list[str] = []
    for p_idx, product in enumerate(normalized.get("tender_products", [])):
        requirements = product.get("requirements")
        if not isinstance(requirements, list):
            continue
        for r_idx, requirement in enumerate(requirements):
            if not isinstance(requirement, dict):
                continue
            if not isinstance(requirement.get("is_hard"), bool):
                violations.append(
                    f"tender_products.{p_idx}.requirements.{r_idx}.is_hard missing or not boolean"
                )
            if require_confidence and not isinstance(
                requirement.get("hardness_confidence"), (int, float)
            ):
                violations.append(
                    "tender_products."
                    f"{p_idx}.requirements.{r_idx}.hardness_confidence missing or not numeric"
                )
    if violations:
        raise ValueError("reviewed requirements validation failed: " + "; ".join(violations))
    return normalized


def validate_hardness_review_payload(payload: dict) -> dict:
    try:
        parsed = HardnessReviewPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            _validation_error_message("hardness review validation failed", exc)
        ) from exc
    return parsed.model_dump(mode="python")


def validate_schema_payload(payload: dict) -> dict:
    try:
        parsed = SchemaPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(_validation_error_message("schema validation failed", exc)) from exc
    return parsed.model_dump(mode="python")


def validate_sql_queries_payload(payload: dict, allowed_tables: set[str] | None = None) -> dict:
    try:
        parsed = SQLQueriesPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(_validation_error_message("sql payload validation failed", exc)) from exc

    normalized = parsed.model_dump(mode="python")
    if allowed_tables is None:
        return normalized

    for item in normalized["queries"]:
        item["sql"] = validate_safe_select_sql(item["sql"], allowed_tables=allowed_tables)
    return normalized


def validate_prompt_result_payload(payload: dict) -> dict:
    try:
        parsed = PromptResultPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(_validation_error_message("prompt result validation failed", exc)) from exc
    return parsed.model_dump(mode="python")
