"""Day-of-week routing and ideal-time scheduling (IST).

Uses the stdlib :mod:`zoneinfo` instead of the third-party ``pytz``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.models import PostType

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SUNDAY = 6

# Ideal posting time per day (hour, minute) in IST.
IDEAL_TIME_SUNDAY = (10, 30)
IDEAL_TIME_WEEKDAY = (9, 30)


def post_type_for_day(weekday: int, settings: Settings) -> PostType:
    """Map a weekday (0=Mon … 6=Sun) to the post type to run."""
    if weekday == settings.poll_day:
        return PostType.POLL
    if weekday == settings.carousel_day:
        return PostType.CAROUSEL
    if weekday == settings.personal_story_day:
        return PostType.STORY
    return PostType.REGULAR


def ideal_time_for(now: datetime) -> tuple[int, int]:
    """Return the (hour, minute) IST target for the given moment's weekday."""
    return IDEAL_TIME_SUNDAY if now.weekday() == SUNDAY else IDEAL_TIME_WEEKDAY


def seconds_until_ideal(now: datetime) -> float:
    """Seconds to wait until the ideal posting time, or 0 if already past."""
    hour, minute = ideal_time_for(now)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return max(0.0, (target - now).total_seconds())


async def wait_for_ideal_time(notify=None) -> None:
    """Sleep until the ideal posting time for today (IST).

    :param notify: optional async callable invoked with a user-facing message
        when a wait is required.
    """
    now = datetime.now(IST)
    wait_seconds = seconds_until_ideal(now)
    if wait_seconds <= 0:
        return

    hour, minute = ideal_time_for(now)
    wait_minutes = int(wait_seconds // 60)
    logger.info("Scheduled post: waiting %d min until %02d:%02d IST", wait_minutes, hour, minute)
    if notify is not None:
        from app import strings

        await notify(strings.scheduled_wait(hour, minute, wait_minutes))
    await asyncio.sleep(wait_seconds)
