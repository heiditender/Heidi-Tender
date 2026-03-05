import logging
import sys
from typing import Any


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def log_kv(logger: logging.Logger, event: str, **kwargs: Any) -> None:
    payload = " ".join([f"{k}={v}" for k, v in kwargs.items()])
    logger.info("%s %s", event, payload)
