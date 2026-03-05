#!/usr/bin/env python
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.core.config import get_settings
from apps.api.core.logging import setup_logging
from apps.api.models.db import SessionLocal
from apps.api.services.indexing.qdrant_client import ensure_collection
from apps.api.services.indexing.upsert import reindex_notices


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    ensure_collection()

    with SessionLocal() as db:
        stats = reindex_notices(db, notice_ids=None, full=True)

    print("Reindex result:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
