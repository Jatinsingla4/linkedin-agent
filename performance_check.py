"""
performance_check.py — Daily script to send performance reminders.

Checks state.json for posts published ~24h ago and sends
a Telegram reminder to manually check likes/comments.
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

from orchestrator import Orchestrator


async def main():
    orchestrator = Orchestrator()
    await orchestrator.send_performance_reminders()
    logging.info("Performance check done")


if __name__ == "__main__":
    asyncio.run(main())
