"""
calendar_planner.py — Sunday content calendar planner.

Generates 4 topic ideas for the coming week (Tue/Thu/Sat/Sun posts),
sends them to Telegram for approval, then saves approved topics
to agent_state.json content_queue for the orchestrator to consume.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from config.settings import config
from src.content_writer import ContentWriter
from src.approval_bot import ApprovalBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", mode="a"),
    ]
)
logger = logging.getLogger("calendar_planner")

STATE_FILE = Path("agent_state.json")


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"State load failed: {e}")
    return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError as e:
        logger.warning(f"State save failed: {e}")


async def main():
    logger.info("=" * 60)
    logger.info("📅 Content Calendar Planner — Sunday Edition")
    logger.info("=" * 60)

    writer = ContentWriter()
    bot = ApprovalBot()

    await bot.send_notification(
        "📅 *Sunday Planning Mode*\n"
        "Generating this week's content calendar...\n"
        "_Give me ~30 seconds_"
    )

    try:
        topics = await writer.generate_weekly_topics(count=4)
    except Exception as e:
        logger.error(f"Topic generation failed: {e}")
        await bot.send_notification(f"❌ Calendar planning failed: `{str(e)[:200]}`")
        return

    approved_topics = await bot.request_calendar_approval(topics)

    if not approved_topics:
        logger.info("Calendar plan rejected — queue not updated")
        return

    state = _load_state()
    existing_queue = state.get("content_queue", [])
    state["content_queue"] = existing_queue + approved_topics
    _save_state(state)

    logger.info(f"Content queue updated: {len(state['content_queue'])} topics total")
    await bot.send_notification(
        f"✅ *{len(approved_topics)} topics queued for this week!*\n"
        + "\n".join(f"• {t[:70]}" for t in approved_topics)
    )


if __name__ == "__main__":
    asyncio.run(main())
