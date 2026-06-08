"""Centralised, validated configuration.

All environment variables are read and validated here exactly once. Required
variables raise a descriptive :class:`EnvironmentError` at startup if missing or
left at a ``your_*`` placeholder.

Import the module-level :data:`settings` singleton everywhere, or construct a
fresh :class:`Settings` in tests with overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


class ConfigError(EnvironmentError):
    """Raised when a required configuration value is missing or invalid."""


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value or value.startswith("your_"):
        raise ConfigError(
            f"\n\n❌  Missing required environment variable: {key}\n"
            f"    Set it in your .env file (see .env.example).\n"
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    raw = _optional(key, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    return _optional(key, str(default)).lower() in ("1", "true", "yes", "on")


def _csv(key: str, default: str) -> list[str]:
    return [item.strip() for item in _optional(key, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, loaded from the environment."""

    # ── Gemini ───────────────────────────────────────────────
    gemini_api_key: str = field(default_factory=lambda: _require("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _optional("GEMINI_MODEL", "gemini-2.5-flash"))

    # ── LinkedIn ─────────────────────────────────────────────
    linkedin_client_id: str = field(default_factory=lambda: _require("LINKEDIN_CLIENT_ID"))
    linkedin_client_secret: str = field(default_factory=lambda: _require("LINKEDIN_CLIENT_SECRET"))
    linkedin_access_token: str = field(default_factory=lambda: _require("LINKEDIN_ACCESS_TOKEN"))
    linkedin_person_urn: str = field(default_factory=lambda: _require("LINKEDIN_PERSON_URN"))

    # ── Telegram ─────────────────────────────────────────────
    telegram_bot_token: str = field(default_factory=lambda: _require("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _require("TELEGRAM_CHAT_ID"))

    # ── Unsplash ─────────────────────────────────────────────
    unsplash_access_key: str = field(default_factory=lambda: _require("UNSPLASH_ACCESS_KEY"))

    # ── Agent behaviour ──────────────────────────────────────
    posts_per_week: int = field(default_factory=lambda: _int("POSTS_PER_WEEK", 4))
    approval_timeout_hours: int = field(default_factory=lambda: _int("APPROVAL_TIMEOUT_HOURS", 12))
    generate_versions: int = field(default_factory=lambda: _int("GENERATE_VERSIONS", 2))
    enable_first_comment: bool = field(default_factory=lambda: _bool("ENABLE_FIRST_COMMENT", True))
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))

    # Day-of-week routing: 0=Mon … 6=Sun
    personal_story_day: int = field(default_factory=lambda: _int("PERSONAL_STORY_DAY", 3))
    poll_day: int = field(default_factory=lambda: _int("POLL_DAY", 6))
    carousel_day: int = field(default_factory=lambda: _int("CAROUSEL_DAY", 5))

    # ── Personal branding ────────────────────────────────────
    your_name: str = field(default_factory=lambda: _optional("YOUR_NAME", "Jatin"))
    your_role: str = field(
        default_factory=lambda: _optional("YOUR_ROLE", "Digital Marketing & Brand Strategist")
    )
    your_company: str = field(default_factory=lambda: _optional("YOUR_COMPANY", "Grapes Worldwide"))
    your_niche: list[str] = field(
        default_factory=lambda: _csv(
            "YOUR_LINKEDIN_NICHE", "marketing,branding,AI,FMCG,agency life,startup"
        )
    )

    # ── LinkedIn API endpoints ───────────────────────────────
    linkedin_api_base: str = "https://api.linkedin.com/v2"

    @property
    def linkedin_ugc_posts_url(self) -> str:
        return f"{self.linkedin_api_base}/ugcPosts"

    @property
    def linkedin_assets_url(self) -> str:
        return f"{self.linkedin_api_base}/assets?action=registerUpload"


# Singleton — import this everywhere outside of tests.
settings = Settings()
