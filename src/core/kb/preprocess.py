#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

from .common import iso_now, sha256_file, write_json

DIRECT_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".json",
    ".html",
    ".xml",
    ".doc",
    ".docx",
    ".rtf",
    ".odt",
    ".ppt",
    ".pptx",
    ".csv",
    ".xls",
    ".xlsx",
    ".ods",
}

PROPRIETARY_EXTENSIONS = {".rdf", ".rel", ".ldt"}
TEXTLIKE_PROPRIETARY = {".rel", ".ldt"}

LOW_VALUE_EXTENSIONS = {
    ".log",
    ".bak",
    ".lnk",
    ".exe",
    ".dll",
    ".dmp",
    ".wmf",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".psd",
    ".wmv",
    ".m4a",
    ".3ds",
    ".dwl",
    ".gg",
    ".rolf",
    ".rof",
    ".ini",
    ".inf",
    ".url",
    ".db",
    ".mdb",
    ".rdb",
    ".msg",
}

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DEFAULT_SRC = (
    "/home/daz/all_things_for_genai_hackathon/"
    "Light norms and recomandations-20260309T141701Z-3"
)
DEFAULT_DST = "/home/daz/all_things_for_genai_hackathon/light_kb_minimal_preprocessed"


def is_probably_text(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096]
    except Exception:
        return False
    if b"\x00" in sample:
        return False
    if not sample:
        return True
    printable = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126)
    return printable / max(1, len(sample)) > 0.8


def read_text_lossy(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def extract_strings(path: Path, min_len: int = 8) -> list[str]:
    try:
        result = subprocess.run(
            ["strings", "-n", str(min_len), str(path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    lines: list[str] = []
    seen = set()
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def rel_section(rel_path: Path) -> str:
    parts = [p for p in rel_path.parts if p]
    if not parts:
        return "unknown"
    if parts[0] == "Light norms and recomandations" and len(parts) > 1:
        return parts[1]
    return parts[0]


def year_hint(path: Path) -> str | None:
    text = str(path)
    match = YEAR_RE.search(text)
    if not match:
        return None
    return match.group(0)


def preprocess(src: Path, dst: Path, force: bool = False) -> dict:
    if not src.exists():
        raise FileNotFoundError(f"Source directory not found: {src}")

    if dst.exists() and any(dst.iterdir()):
        if not force:
            raise RuntimeError(f"Destination is not empty: {dst}. Use --force to overwrite.")
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    corpus_dir = dst / "upload_corpus"
    reports_dir = dst / "reports"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    supported_by_hash: dict[str, Path] = {}
    converted_by_hash: dict[str, Path] = {}
    skipped_rows: list[tuple[str, str, str]] = []
    duplicate_rows: list[tuple[str, str, str]] = []
    manifest_rows: list[dict] = []
    pdf_rows: list[str] = []

    total_files = 0
    direct_kept = 0
    converted_kept = 0
    source_bytes_total = 0
    output_bytes_total = 0

    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        total_files += 1
        ext = path.suffix.lower()
        rel = path.relative_to(src)
        rel_str = rel.as_posix()
        size = path.stat().st_size
        source_bytes_total += size

        if ext in LOW_VALUE_EXTENSIONS:
            skipped_rows.append((rel_str, ext or "(noext)", "low_value"))
            continue

        if ext in DIRECT_UPLOAD_EXTENSIONS:
            digest = sha256_file(path)
            if digest in supported_by_hash:
                duplicate_rows.append(
                    (rel_str, supported_by_hash[digest].as_posix(), "duplicate_direct")
                )
                continue
            target = corpus_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            out_size = target.stat().st_size
            output_bytes_total += out_size
            supported_by_hash[digest] = target.relative_to(dst)
            direct_kept += 1
            if ext == ".pdf":
                pdf_rows.append(target.relative_to(dst).as_posix())
            manifest_rows.append(
                {
                    "path": target.relative_to(dst).as_posix(),
                    "source_path": rel_str,
                    "ingestion_type": "direct",
                    "sha256": digest,
                    "ext": ext,
                    "size_bytes": out_size,
                    "section": rel_section(rel),
                    "year_hint": year_hint(rel),
                }
            )
            continue

        if ext in PROPRIETARY_EXTENSIONS:
            digest = sha256_file(path)
            if digest in converted_by_hash:
                duplicate_rows.append(
                    (rel_str, converted_by_hash[digest].as_posix(), "duplicate_converted")
                )
                continue

            target = corpus_dir / rel.parent / f"{rel.name}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            header = [
                f"# source_path: {rel_str}",
                f"# source_ext: {ext}",
                "# ingestion_type: converted_proprietary",
                f"# generated_at: {iso_now()}",
                "",
            ]

            content = ""
            method = ""
            if ext in TEXTLIKE_PROPRIETARY and is_probably_text(path):
                content = read_text_lossy(path)
                method = "text_decode"
            else:
                lines = extract_strings(path, min_len=8)
                if lines:
                    max_lines = 8000
                    max_chars = 400_000
                    lines = lines[:max_lines]
                    clipped: list[str] = []
                    total_chars = 0
                    for line in lines:
                        total_chars += len(line)
                        if total_chars > max_chars:
                            break
                        clipped.append(line)
                    content = "\n".join(clipped)
                    method = "strings"
                else:
                    content = "[no extractable text found]"
                    method = "none"

            target.write_text("\n".join(header) + content + "\n", encoding="utf-8")
            out_size = target.stat().st_size
            output_bytes_total += out_size
            converted_kept += 1
            converted_by_hash[digest] = target.relative_to(dst)
            manifest_rows.append(
                {
                    "path": target.relative_to(dst).as_posix(),
                    "source_path": rel_str,
                    "ingestion_type": "converted_proprietary",
                    "conversion_method": method,
                    "sha256": digest,
                    "ext": ext,
                    "size_bytes": out_size,
                    "section": rel_section(rel),
                    "year_hint": year_hint(rel),
                }
            )
            continue

        skipped_rows.append((rel_str, ext or "(noext)", "unsupported_extension"))

    skipped_tsv = reports_dir / "skipped.tsv"
    duplicates_tsv = reports_dir / "duplicates.tsv"
    manifest_jsonl = reports_dir / "manifest_upload.jsonl"
    ocr_pending = reports_dir / "pdf_ocr_pending.txt"

    with skipped_tsv.open("w", encoding="utf-8") as fh:
        fh.write("source_path\text\treason\n")
        for row in skipped_rows:
            fh.write("\t".join(row) + "\n")

    with duplicates_tsv.open("w", encoding="utf-8") as fh:
        fh.write("source_path\tkept_path\treason\n")
        for row in duplicate_rows:
            fh.write("\t".join(row) + "\n")

    with manifest_jsonl.open("w", encoding="utf-8") as fh:
        for row in manifest_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    ocr_tools = {
        "ocrmypdf": shutil.which("ocrmypdf") is not None,
        "pdftotext": shutil.which("pdftotext") is not None,
        "tesseract": shutil.which("tesseract") is not None,
    }
    with ocr_pending.open("w", encoding="utf-8") as fh:
        fh.write("# OCR status for staged PDF files\n")
        fh.write(f"# generated_at: {iso_now()}\n")
        fh.write(
            "# note: OCR not executed because required tools are missing"
            if not all(ocr_tools.values())
            else "# note: OCR tools detected; run OCR pipeline separately if needed"
        )
        fh.write("\n")
        for row in pdf_rows:
            fh.write(row + "\n")

    summary = {
        "generated_at": iso_now(),
        "source_dir": str(src),
        "destination_dir": str(dst),
        "counts": {
            "total_source_files": total_files,
            "direct_kept_files": direct_kept,
            "converted_proprietary_files": converted_kept,
            "manifest_rows": len(manifest_rows),
            "skipped_files": len(skipped_rows),
            "duplicate_files": len(duplicate_rows),
            "staged_pdf_files": len(pdf_rows),
        },
        "bytes": {
            "source_bytes_total": source_bytes_total,
            "output_bytes_total": output_bytes_total,
        },
        "ocr_tools_available": ocr_tools,
        "reports": {
            "manifest_upload_jsonl": str(manifest_jsonl),
            "skipped_tsv": str(skipped_tsv),
            "duplicates_tsv": str(duplicates_tsv),
            "pdf_ocr_pending": str(ocr_pending),
        },
    }
    write_json(reports_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal preprocessing for lighting KB ingestion.")
    parser.add_argument("--src", default=DEFAULT_SRC, help="Source knowledge base directory")
    parser.add_argument("--dst", default=DEFAULT_DST, help="Destination directory for staged corpus")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete destination directory first if it already contains files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()

    summary = preprocess(src=src, dst=dst, force=args.force)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
