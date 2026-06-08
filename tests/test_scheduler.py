"""Scheduler: weekday→post-type routing and ideal-time maths."""

from __future__ import annotations

from datetime import datetime

from app.core import scheduler
from app.core.scheduler import IST
from app.models import PostType
from tests.conftest import make_settings


def test_post_type_routing():
    s = make_settings(personal_story_day=3, poll_day=6, carousel_day=5)
    assert scheduler.post_type_for_day(0, s) == PostType.REGULAR  # Monday
    assert scheduler.post_type_for_day(3, s) == PostType.STORY     # Thursday
    assert scheduler.post_type_for_day(5, s) == PostType.CAROUSEL  # Saturday
    assert scheduler.post_type_for_day(6, s) == PostType.POLL      # Sunday


def test_ideal_time_sunday_vs_weekday():
    sunday = datetime(2026, 6, 7, 8, 0, tzinfo=IST)   # a Sunday
    monday = datetime(2026, 6, 8, 8, 0, tzinfo=IST)   # a Monday
    assert scheduler.ideal_time_for(sunday) == (10, 30)
    assert scheduler.ideal_time_for(monday) == (9, 30)


def test_seconds_until_ideal_before_and_after():
    monday_early = datetime(2026, 6, 8, 8, 0, tzinfo=IST)  # before 9:30
    monday_late = datetime(2026, 6, 8, 11, 0, tzinfo=IST)  # after 9:30
    assert scheduler.seconds_until_ideal(monday_early) == 90 * 60
    assert scheduler.seconds_until_ideal(monday_late) == 0
