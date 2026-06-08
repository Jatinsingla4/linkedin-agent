"""Run the full posting pipeline once.

    python -m entrypoints.run_agent
"""

from __future__ import annotations

import asyncio
import logging

from app.core.lock import LockHeldError, single_instance
from app.logging_config import setup_logging
from app.orchestrator import Orchestrator

logger = logging.getLogger("run_agent")


async def main() -> None:
    setup_logging()
    try:
        with single_instance():
            await Orchestrator().run()
    except LockHeldError as e:
        logger.warning("Skipping run: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
