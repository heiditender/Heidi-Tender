from __future__ import annotations

import json
from pathlib import Path


def write_debug_text(debug_dir: Path, name: str, text: str) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(text, encoding="utf-8")


def write_debug_json(debug_dir: Path, name: str, payload: dict) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

