#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from .common import iso_now, load_jsonl, write_json
from .preprocess import DEFAULT_DST, DEFAULT_SRC, preprocess as run_preprocess

DEFAULT_BASE = Path(DEFAULT_DST)

TRAINING_KEYWORDS = (
    "demo",
    "students",
    "sample",
    "lehrgangsarbeit",
    "übungsaufgaben",
    "uebungsaufgaben",
)

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")


def load_low_text_pdf_set(path: Path) -> set[str]:
    # Matches manifest.source_path format, e.g.:
    # "Light norms and recomandations/.../foo.pdf"
    items: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        items.add(value)
    return items


def is_training_or_demo(path_value: str) -> bool:
    lower = path_value.lower()
    return any(keyword in lower for keyword in TRAINING_KEYWORDS)


def infer_source(row: dict) -> str:
    source_path = str(row.get("source_path") or "")
    parts = [p for p in source_path.split("/") if p]
    if not parts:
        return "unknown"
    if parts[0] == "Light norms and recomandations" and len(parts) > 1:
        return parts[1]
    return parts[0]


def infer_doc_kind(row: dict) -> str:
    ext = str(row.get("ext") or "").lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".doc", ".docx", ".rtf", ".odt"}:
        return "word_like"
    if ext in {".ppt", ".pptx"}:
        return "slide"
    if ext in {".xls", ".xlsx", ".ods", ".csv"}:
        return "tabular"
    if ext == ".rdf":
        return "relux_project_container_text_extract"
    if ext == ".rel":
        return "eulumdat_rel_text_extract"
    if ext == ".ldt":
        return "eulumdat_ldt_text_extract"
    return "other"


def infer_topic(row: dict) -> str:
    text = (str(row.get("source_path") or "") + " " + str(row.get("path") or "")).lower()
    if "notbeleuchtung" in text or "sicherheitsbeleuchtung" in text:
        return "emergency_lighting"
    if "tageslicht" in text:
        return "daylight"
    if "led forum" in text or "/led/" in text:
        return "led"
    if "sport" in text:
        return "sports_lighting"
    if "norm" in text:
        return "norms_and_standards"
    return "general_lighting"


def infer_lang_hint(row: dict) -> str:
    text = (str(row.get("source_path") or "") + " " + str(row.get("path") or "")).lower()
    de_markers = (" und ", "für", "über", "licht", "beleuchtung", "normen", "leuchten")
    en_markers = (" lighting ", "standard", "guide", "seminar", "workshop")
    de_hits = sum(1 for marker in de_markers if marker in text)
    en_hits = sum(1 for marker in en_markers if marker in text)
    if de_hits > en_hits and de_hits >= 1:
        return "de"
    if en_hits > de_hits and en_hits >= 1:
        return "en"
    return "unknown"


def link_or_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def extract_pdf_text(pdf_path: Path, timeout_sec: int = 60) -> tuple[str, str, str]:
    try:
        result = subprocess.run(
            ["mutool", "draw", "-F", "txt", str(pdf_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return "", "timeout", str(exc)
    except Exception as exc:
        return "", "error", str(exc)
    if result.returncode != 0:
        return "", "error", (result.stderr or "").strip()[:500]
    return result.stdout or "", "ok", ""


def build_low_text_pdf_reports(base_dir: Path, threshold: int = 20) -> dict:
    mutool_path = shutil.which("mutool")
    if not mutool_path:
        raise RuntimeError("mutool is required for low-text PDF detection but was not found in PATH")

    reports_dir = base_dir / "reports"
    manifest_path = reports_dir / "manifest_upload.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    rows = load_jsonl(manifest_path)
    pdf_rows = [r for r in rows if str(r.get("ext") or "").lower() == ".pdf"]

    details: list[dict] = []
    low_lt20_source_paths: list[str] = []
    low_lt100_source_paths: list[str] = []
    ok_count = 0
    fail_count = 0

    for row in pdf_rows:
        rel_path = Path(str(row.get("path") or ""))
        source_path = str(row.get("source_path") or "")
        pdf_path = base_dir / rel_path
        text, status, error = extract_pdf_text(pdf_path)
        chars = len(text.strip())
        words = len(WORD_RE.findall(text))
        if status == "ok":
            ok_count += 1
        else:
            fail_count += 1

        if chars < threshold:
            low_lt20_source_paths.append(source_path)
        if chars < 100:
            low_lt100_source_paths.append(source_path)

        details.append(
            {
                "source_path": source_path,
                "path": str(rel_path),
                "chars_full": chars,
                "words_full": words,
                "status": status,
                "error": error if error else None,
            }
        )

    # De-duplicate while keeping order.
    def ordered_unique(values: list[str]) -> list[str]:
        out: list[str] = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    low_lt20_source_paths = ordered_unique(low_lt20_source_paths)
    low_lt100_source_paths = ordered_unique(low_lt100_source_paths)

    scan_stats = {
        "generated_at": iso_now(),
        "threshold_lt20": threshold,
        "total_pdf_in_manifest": len(pdf_rows),
        "extract_ok": ok_count,
        "extract_fail": fail_count,
        "lt20_count": len(low_lt20_source_paths),
        "lt100_count": len(low_lt100_source_paths),
        "mutool_path": mutool_path,
    }

    write_json(reports_dir / "pdf_low_text_full_scan.json", details)
    write_json(reports_dir / "pdf_low_text_full_scan_stats.json", scan_stats)
    (reports_dir / "pdf_low_text_lt20_paths.txt").write_text(
        "\n".join(low_lt20_source_paths) + ("\n" if low_lt20_source_paths else ""),
        encoding="utf-8",
    )
    (reports_dir / "pdf_low_text_lt100_paths.txt").write_text(
        "\n".join(low_lt100_source_paths) + ("\n" if low_lt100_source_paths else ""),
        encoding="utf-8",
    )
    return scan_stats


def build_kb(base_dir: Path, force: bool) -> dict:
    input_manifest = base_dir / "reports" / "manifest_upload.jsonl"
    low_text_pdf_list = base_dir / "reports" / "pdf_low_text_lt20_paths.txt"
    output_corpus = base_dir / "upload_corpus_kb"
    output_reports = base_dir / "reports_kb"

    if not input_manifest.exists():
        raise FileNotFoundError(f"Missing input manifest: {input_manifest}")
    if not low_text_pdf_list.exists():
        raise FileNotFoundError(f"Missing low-text PDF list: {low_text_pdf_list}")

    if output_corpus.exists():
        if not force:
            raise RuntimeError(f"Destination exists: {output_corpus}. Use --force to overwrite.")
        shutil.rmtree(output_corpus)
    if output_reports.exists() and force:
        shutil.rmtree(output_reports)
    output_corpus.mkdir(parents=True, exist_ok=True)
    output_reports.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(input_manifest)
    low_text_pdf_set = load_low_text_pdf_set(low_text_pdf_list)

    kept_rows: list[dict] = []
    dropped_rows: list[dict] = []
    action_counter: Counter[str] = Counter()

    for row in rows:
        path_in_base = Path(str(row.get("path") or ""))
        source_path = str(row.get("source_path") or "")
        ext = str(row.get("ext") or "").lower()
        path_text = str(path_in_base).lower()

        reasons: list[str] = []
        if path_text.endswith(".ldt.txt"):
            reasons.append("drop_ldt_txt_noise")
        if path_text.endswith(".rel.txt"):
            reasons.append("drop_rel_txt_noise")
        if is_training_or_demo(source_path):
            reasons.append("drop_training_or_demo_path")
        if ext == ".pdf" and source_path in low_text_pdf_set:
            reasons.append("drop_low_text_pdf_lt20")

        if reasons:
            dropped_rows.append(
                {
                    "path": str(path_in_base),
                    "source_path": source_path,
                    "ext": ext,
                    "reasons": reasons,
                }
            )
            for reason in reasons:
                action_counter[reason] += 1
            continue

        if not str(path_in_base).startswith("upload_corpus/"):
            dropped_rows.append(
                {
                    "path": str(path_in_base),
                    "source_path": source_path,
                    "ext": ext,
                    "reasons": ["invalid_input_path_prefix"],
                }
            )
            action_counter["invalid_input_path_prefix"] += 1
            continue

        rel_inside_corpus = Path(str(path_in_base).replace("upload_corpus/", "", 1))
        src_file = base_dir / path_in_base
        dst_file = output_corpus / rel_inside_corpus
        if not src_file.exists():
            dropped_rows.append(
                {
                    "path": str(path_in_base),
                    "source_path": source_path,
                    "ext": ext,
                    "reasons": ["missing_source_file"],
                }
            )
            action_counter["missing_source_file"] += 1
            continue

        action = link_or_copy(src_file, dst_file)
        action_counter[f"output_{action}"] += 1

        enriched = dict(row)
        enriched["path"] = str(Path("upload_corpus_kb") / rel_inside_corpus)
        enriched["metadata"] = {
            "source": infer_source(row),
            "doc_kind": infer_doc_kind(row),
            "topic": infer_topic(row),
            "lang_hint": infer_lang_hint(row),
            "year_hint": row.get("year_hint"),
        }
        kept_rows.append(enriched)

    manifest_kb = output_reports / "manifest_upload_kb.jsonl"
    dropped_tsv = output_reports / "dropped_kb.tsv"

    with manifest_kb.open("w", encoding="utf-8") as fh:
        for row in kept_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    with dropped_tsv.open("w", encoding="utf-8") as fh:
        fh.write("path\tsource_path\text\treasons\n")
        for row in dropped_rows:
            reason_str = ",".join(row.get("reasons") or [])
            fh.write(
                f"{row.get('path','')}\t{row.get('source_path','')}\t"
                f"{row.get('ext','')}\t{reason_str}\n"
            )

    input_count = len(rows)
    output_count = len(kept_rows)
    dropped_count = len(dropped_rows)
    output_bytes = 0
    for row in kept_rows:
        p = base_dir / row["path"]
        if p.exists():
            output_bytes += p.stat().st_size

    reason_counter: Counter[str] = Counter()
    for row in dropped_rows:
        for reason in row.get("reasons") or []:
            reason_counter[reason] += 1

    summary = {
        "generated_at": iso_now(),
        "base_dir": str(base_dir),
        "input_manifest": str(input_manifest),
        "output_corpus": str(output_corpus),
        "reports_dir": str(output_reports),
        "counts": {
            "input_files": input_count,
            "output_files": output_count,
            "dropped_files": dropped_count,
        },
        "bytes": {
            "output_corpus_bytes": output_bytes,
        },
        "drop_reasons": dict(reason_counter),
        "io_actions": dict(action_counter),
        "outputs": {
            "manifest_upload_kb_jsonl": str(manifest_kb),
            "dropped_kb_tsv": str(dropped_tsv),
        },
    }
    write_json(output_reports / "summary_kb.json", summary)
    return summary


def run_one_shot_pipeline(
    src: Path,
    base_dir: Path,
    force: bool,
    low_text_threshold: int,
    skip_preprocess: bool = False,
    skip_low_text_scan: bool = False,
) -> dict:
    if not skip_preprocess:
        preprocess_summary = run_preprocess(src=src, dst=base_dir, force=force)
    else:
        preprocess_summary = {"skipped": True}

    if not skip_low_text_scan:
        low_text_scan_summary = build_low_text_pdf_reports(base_dir, threshold=low_text_threshold)
    else:
        low_text_scan_summary = {"skipped": True}

    kb_summary = build_kb(base_dir=base_dir, force=force)
    pipeline_summary = {
        "generated_at": iso_now(),
        "src": str(src),
        "base_dir": str(base_dir),
        "steps": {
            "preprocess": preprocess_summary,
            "low_text_pdf_scan": low_text_scan_summary,
            "build_kb": kb_summary,
        },
    }
    write_json(base_dir / "reports_kb" / "pipeline_summary.json", pipeline_summary)
    return pipeline_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot pipeline: run minimal preprocess from raw KB, "
            "auto-detect low-text PDFs, and build upload_corpus_kb."
        )
    )
    parser.add_argument(
        "--src",
        default=DEFAULT_SRC,
        help="Raw source knowledge base directory",
    )
    parser.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE),
        help="Output base directory (upload_corpus, reports, upload_corpus_kb, reports_kb)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing outputs in base-dir",
    )
    parser.add_argument(
        "--low-text-threshold",
        type=int,
        default=20,
        help="PDF chars threshold for dropping low-text PDFs in kb",
    )
    parser.add_argument(
        "--skip-preprocess",
        action="store_true",
        help="Skip raw preprocessing and reuse existing base-dir/upload_corpus + reports",
    )
    parser.add_argument(
        "--skip-low-text-scan",
        action="store_true",
        help="Skip low-text PDF scan and reuse existing reports/pdf_low_text_lt20_paths.txt",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    src = Path(args.src).resolve()
    base_dir = Path(args.base_dir).resolve()

    summary = run_one_shot_pipeline(
        src=src,
        base_dir=base_dir,
        force=args.force,
        low_text_threshold=args.low_text_threshold,
        skip_preprocess=args.skip_preprocess,
        skip_low_text_scan=args.skip_low_text_scan,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
