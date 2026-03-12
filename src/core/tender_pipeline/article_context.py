from __future__ import annotations

import json
import re
from pathlib import Path


def strip_line_comments(raw_text: str) -> str:
    cleaned_lines: list[str] = []
    for line in raw_text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def collect_field_labels(records: dict) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    for item in records.values():
        for field in item.get("fields") or []:
            field_key = field.get("fieldKey")
            if not isinstance(field_key, str) or not field_key:
                continue
            key_obj = field.get("key") or {}
            target = labels.setdefault(field_key, {})
            for lang in ("de", "en", "fr", "it"):
                value = key_obj.get(lang)
                if isinstance(value, str):
                    value = value.strip()
                    if value:
                        target.setdefault(lang, value)
    return labels


def extract_single_record_comment_hints(single_record_raw: str) -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {}
    pending_comment = ""
    for line in single_record_raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            comment = stripped[2:].strip()
            if comment and set(comment) != {"/"}:
                pending_comment = comment
            continue
        match = re.search(r'"fieldKey"\s*:\s*"([^"]+)"', line)
        if match and pending_comment:
            field_key = match.group(1)
            hints.setdefault(field_key, []).append(pending_comment)
            pending_comment = ""
    return hints


def normalize_hint(comment: str) -> str:
    comment_lower = comment.lower()
    percent_match = re.search(r"tolerance\s*([0-9]+(?:\.[0-9]+)?)\s*%", comment_lower)
    if percent_match:
        return (
            f"tolerance +/-{percent_match.group(1)}% "
            "(when tender context allows, use between for tolerance)"
        )
    if "match +/-" in comment_lower:
        delta_match = re.search(r"\+/-\s*([0-9]+(?:\.[0-9]+)?)", comment_lower)
        if delta_match:
            return f"between value-{delta_match.group(1)} and value+{delta_match.group(1)}"
        return "between around the target value"
    if "match or higher" in comment_lower:
        return "gte (higher values generally satisfy minimum threshold)"
    if "match or lower" in comment_lower or "match or smaller" in comment_lower:
        return "lte (lower values generally satisfy upper-bound threshold)"
    if "similar match" in comment_lower:
        return "semantic similarity / contains"
    if "no criteria" in comment_lower:
        return "no strict compliance criterion"
    return comment


def build_article_reference_context(
    single_record_path: Path, multi_record_path: Path
) -> str:
    if not single_record_path.exists() or not multi_record_path.exists():
        return ""
    try:
        single_raw = single_record_path.read_text(encoding="utf-8")
        single_records = json.loads(strip_line_comments(single_raw))
        multi_records = json.loads(multi_record_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    single_labels = collect_field_labels(single_records)
    multi_labels = collect_field_labels(multi_records)
    all_field_keys = sorted(set(single_labels) | set(multi_labels))
    comment_hints = extract_single_record_comment_hints(single_raw)

    lines: list[str] = [
        "Swiss lighting article reference (for requirement extraction only):",
        "- Source A: articles_single_record.json (pseudo-JSON, // comments carry direction/tolerance hints).",
        "- Source B: articles_multi_records.json (multi-product terminology coverage, no comments).",
        "- Rule: this reference helps with terminology/operator; if tender text conflicts, tender text wins.",
        f"- Total common field keys: {len(all_field_keys)}",
        "- Comment-derived direction/tolerance hints:",
    ]

    for field_key in sorted(comment_hints):
        labels = single_labels.get(field_key, {})
        label_bits = []
        if labels.get("de"):
            label_bits.append(f"de={labels['de']}")
        if labels.get("en"):
            label_bits.append(f"en={labels['en']}")
        label_text = "; ".join(label_bits) if label_bits else "de/en label missing"
        normalized = " | ".join(normalize_hint(comment) for comment in comment_hints[field_key])
        lines.append(f"- {field_key} ({label_text}): {normalized}")

    lines.append("- Multilingual terminology map (field_key => de/en):")
    for field_key in all_field_keys:
        labels = single_labels.get(field_key) or multi_labels.get(field_key) or {}
        de = labels.get("de", "")
        en = labels.get("en", "")
        if de or en:
            lines.append(f"- {field_key}: de={de}; en={en}")

    return "\n".join(lines)

