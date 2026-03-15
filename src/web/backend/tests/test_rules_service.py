from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.rules import (
    _build_rule_generation_prompts,
    sanitize_copilot_rule_payload,
    validate_rule_payload,
)


def _valid_rule(*, field: str = "vw_bid_specs.ugr", operator: str = "lte") -> dict:
    return {
        "field": field,
        "operator": operator,
        "is_hard": True,
        "operator_confidence": 0.95,
        "hardness_confidence": 0.9,
        "rationale": "UGR is a primary glare constraint.",
    }


def test_step3_prompt_explicitly_forbids_step2_only_keys() -> None:
    system_prompt, _ = _build_rule_generation_prompts(
        schema_payload={"tables": []},
        allowed_fields={"vw_bid_specs.ugr"},
        user_prompt="",
    )

    assert "Do not output value, unit, source" in system_prompt
    assert "value belongs to Step2 extraction" in system_prompt
    assert '"field_rules"' in system_prompt
    assert "Generate policy rules, not document-specific extracted requirements." in system_prompt
    assert "country-, supplier-, brand-, or project-specific assumptions" in system_prompt


def test_step3_prompt_uses_abstract_example_and_generic_rationale() -> None:
    system_prompt, user_text = _build_rule_generation_prompts(
        schema_payload={"tables": [{"name": "vw_bid_specs", "columns": [{"name": "ugr", "type": "double"}]}]},
        allowed_fields={"vw_bid_specs.ugr"},
        user_prompt="",
    )

    assert '"field":"<allowed_field>"' in system_prompt
    assert "categorical identifier" in system_prompt
    assert "Generate a practical first draft of reusable rules" in user_text
    assert "Swiss" not in system_prompt
    assert "vw_bid_specs.ugr" not in system_prompt


def test_sanitize_copilot_rule_payload_removes_extra_keys() -> None:
    payload = {
        "field_rules": [
            {
                **_valid_rule(),
                "value": 19,
                "unit": None,
            }
        ]
    }

    sanitized, warnings = sanitize_copilot_rule_payload(payload)

    assert sanitized["field_rules"][0] == _valid_rule()
    assert warnings == ["Removed unsupported Copilot keys from 1 row: unit, value."]


def test_sanitize_copilot_rule_payload_is_noop_for_valid_payload() -> None:
    payload = {"field_rules": [_valid_rule()]}

    sanitized, warnings = sanitize_copilot_rule_payload(payload)

    assert sanitized == payload
    assert warnings == []


@pytest.mark.parametrize(
    ("payload", "allowed_fields", "expected_message"),
    [
        (
            {
                "field_rules": [
                    {**_valid_rule(field="vw_bid_specs.ugr"), "value": 19},
                    {**_valid_rule(field="vw_bid_specs.ugr", operator="eq"), "value": 22},
                ]
            },
            {"vw_bid_specs.ugr"},
            "duplicate field in step3 field_rules",
        ),
        (
            {
                "field_rules": [
                    {**_valid_rule(operator="approx"), "value": 19},
                ]
            },
            {"vw_bid_specs.ugr"},
            "invalid field rules payload",
        ),
        (
            {
                "field_rules": [
                    {**_valid_rule(field="vw_bid_specs.unknown"), "value": 19},
                ]
            },
            {"vw_bid_specs.ugr"},
            "non-schema fields",
        ),
    ],
)
def test_validation_stays_strict_after_sanitization(
    payload: dict,
    allowed_fields: set[str],
    expected_message: str,
) -> None:
    sanitized, warnings = sanitize_copilot_rule_payload(payload)

    assert warnings
    with pytest.raises(HTTPException) as excinfo:
        validate_rule_payload(sanitized, allowed_fields)

    assert excinfo.value.status_code == 422
    assert expected_message in str(excinfo.value.detail)
