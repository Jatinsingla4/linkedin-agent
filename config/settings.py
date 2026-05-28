"""
config.py — Centralised configuration with validation.
All env vars are loaded and validated here. Any missing
required variable raises a clear error at startup.
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Fetch a required env variable or raise a descriptive error."""
    value = os.getenv(key, "").strip()
    if not value or value.startswith("your_"):
        raise EnvironmentError(
            f"\n\n❌  Missing required environment variable: {key}\n"
            f"    Please set it in your .env file.\n"
            f"    See .env.example for reference.\n"
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass
class Config:
    # ── Gemini ──────────────────────────────────────────────
    gemini_api_key: str = field(default_factory=lambda: _require("GEMINI_API_KEY"))
    gemini_model: str = "gemini-2.5-flash"

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

    # ── Agent Behaviour ──────────────────────────────────────
    posts_per_week: int = field(default_factory=lambda: int(_optional("POSTS_PER_WEEK", "4")))
    approval_timeout_hours: int = field(default_factory=lambda: int(_optional("APPROVAL_TIMEOUT_HOURS", "12")))
    generate_versions: int = field(default_factory=lambda: int(_optional("GENERATE_VERSIONS", "2")))
    enable_first_comment: bool = field(default_factory=lambda: _optional("ENABLE_FIRST_COMMENT", "true").lower() == "true")
    personal_story_day: int = field(default_factory=lambda: int(_optional("PERSONAL_STORY_DAY", "3")))  # 0=Mon…6=Sun; 3=Thu
    poll_day: int = field(default_factory=lambda: int(_optional("POLL_DAY", "6")))                      # 6=Sun
    carousel_day: int = field(default_factory=lambda: int(_optional("CAROUSEL_DAY", "5")))              # 5=Sat

    # ── Personal Branding ────────────────────────────────────
    your_name: str = field(default_factory=lambda: _optional("YOUR_NAME", "Jatin"))
    your_role: str = field(default_factory=lambda: _optional("YOUR_ROLE", "Digital Marketing & Brand Strategist"))
    your_company: str = field(default_factory=lambda: _optional("YOUR_COMPANY", "Grapes Worldwide"))
    your_niche: List[str] = field(default_factory=lambda: [
        t.strip() for t in _optional(
            "YOUR_LINKEDIN_NICHE",
            "marketing,branding,AI,FMCG,agency life,startup"
        ).split(",")
    ])

    # ── LinkedIn API endpoints ───────────────────────────────
    linkedin_api_base: str = "https://api.linkedin.com/v2"
    linkedin_ugc_posts_url: str = "https://api.linkedin.com/v2/ugcPosts"
    linkedin_assets_url: str = "https://api.linkedin.com/v2/assets?action=registerUpload"


# Singleton — import this everywhere
config = Config()
