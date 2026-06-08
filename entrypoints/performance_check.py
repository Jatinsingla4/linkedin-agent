"""Send engagement reminders for posts published ~24h ago.

    python -m entrypoints.performance_check
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.core.state import StateStore
from app.logging_config import setup_logging
from app.reporting import Reporting
from app.services.telegram_bot import ApprovalBot

logger = logging.getLogger("performance_check")


async def main() -> None:
    setup_logging()
    reporting = Reporting(StateStore(), ApprovalBot(settings))
    await reporting.send_performance_reminders()
    logger.info("Performance check done")


if __name__ == "__main__":
    asyncio.run(main())
