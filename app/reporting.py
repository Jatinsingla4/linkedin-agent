"""Performance reminders and the Sunday weekly report."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from app import strings
from app.core.scheduler import SUNDAY
from app.core.state import StateStore
from app.services.telegram_bot import ApprovalBot

logger = logging.getLogger(__name__)

REMINDER_MIN_HOURS = 20
REMINDER_MAX_HOURS = 28


class Reporting:
    def __init__(self, state: StateStore, approval_bot: ApprovalBot):
        self._state = state
        self._bot = approval_bot

    async def send_performance_reminders(self) -> None:
        """Nudge the user ~24h after a post to check its engagement."""
        now = datetime.now(UTC)
        changed = False
        for post in self._state.get("recent_posts", []):
            if post.get("reminder_sent"):
                continue
            published = datetime.fromisoformat(post["published_at"])
            age_hours = (now - published).total_seconds() / 3600
            if REMINDER_MIN_HOURS <= age_hours <= REMINDER_MAX_HOURS:
                await self._bot.send_notification(
                    strings.performance_check(post["topic"], post.get("url", ""))
                )
                post["reminder_sent"] = True
                changed = True
        if changed:
            self._state.save()

    async def maybe_send_weekly_report(self) -> None:
        """On Sundays, send a one-per-day summary and reset the weekly counter."""
        if datetime.now(UTC).weekday() != SUNDAY:
            return
        today = date.today().isoformat()
        if self._state.get("last_weekly_report") == today:
            return

        await self._bot.send_notification(
            strings.weekly_report(
                this_week=self._state.get("posts_this_week", 0),
                total=self._state.get("posts_published", 0),
                last_post=self._state.get("last_post_at", "Never"),
            )
        )
        self._state.set("last_weekly_report", today)
        self._state.set("posts_this_week", 0)
