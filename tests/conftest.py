"""Shared test fixtures.

Tests never touch the network or real credentials. ``make_settings`` builds a
fully-specified :class:`Settings` with dummy values so no environment variables
are read.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def make_settings(**overrides) -> Settings:
    base = dict(
        gemini_api_key="test-gemini",
        gemini_model="gemini-2.0-flash",
        linkedin_client_id="cid",
        linkedin_client_secret="secret",
        linkedin_access_token="token",
        linkedin_person_urn="urn:li:person:ABC123",
        telegram_bot_token="123:abc",
        telegram_chat_id="999",
        unsplash_access_key="unsplash",
        posts_per_week=4,
        approval_timeout_hours=12,
        generate_versions=2,
        enable_first_comment=True,
        dry_run=True,
        personal_story_day=3,
        poll_day=6,
        carousel_day=5,
        your_name="Jatin",
        your_role="Brand Strategist",
        your_company="Grapes Worldwide",
        your_niche=["marketing", "branding", "ai"],
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


class FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    def __init__(self, status: int, *, headers: dict | None = None, body: str = ""):
        self.status = status
        self.headers = headers or {}
        self._body = body

    async def text(self) -> str:
        return self._body
