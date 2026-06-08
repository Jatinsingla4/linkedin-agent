"""Sunday content calendar planner.

Generates topic ideas for the week, gets Telegram approval, and queues the
approved topics for the orchestrator to consume.

    python -m entrypoints.plan_calendar
"""

from __future__ import annotations

import asyncio
import logging

from app import strings
from app.config import settings
from app.core.state import StateStore
from app.logging_config import setup_logging
from app.services.content.writer import ContentWriter
from app.services.gemini_client import GeminiClient
from app.services.telegram_bot import ApprovalBot

logger = logging.getLogger("plan_calendar")


async def main() -> None:
    setup_logging()
    logger.info("📅 Content Calendar Planner — Sunday Edition")

    writer = ContentWriter(settings, GeminiClient(settings))
    bot = ApprovalBot(settings)
    state = StateStore()

    await bot.send_notification(strings.CALENDAR_PLANNING)

    try:
        topics = await writer.generate_weekly_topics(count=4)
    except Exception as e:
        logger.error("Topic generation failed: %s", e)
        await bot.send_notification(strings.calendar_failed(str(e)))
        return

    approved = await bot.request_calendar_approval(topics)
    if not approved:
        logger.info("Calendar plan rejected — queue not updated")
        return

    state.extend_queue(approved)
    logger.info("Content queue updated: %d topics total", len(state.get("content_queue", [])))
    await bot.send_notification(strings.calendar_queued(approved))


if __name__ == "__main__":
    asyncio.run(main())
