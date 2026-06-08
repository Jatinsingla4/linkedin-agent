"""Single logging configuration used by every entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False
LOG_FILE = Path("agent.log")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once: stdout + appended ``agent.log``.

    Idempotent — safe to call from multiple entry points.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        ],
    )
    # Quieten noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    _CONFIGURED = True
