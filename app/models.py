"""Shared domain models.

Every dataclass and enum that crosses a module boundary lives here so the rest
of the codebase depends on data shapes, not on each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PostType(StrEnum):
    """Which pipeline runs for a given day."""

    REGULAR = "regular"
    STORY = "story"
    POLL = "poll"
    CAROUSEL = "carousel"


@dataclass
class Topic:
    title: str
    source: str
    summary: str | None = None
    url: str | None = None
    relevance_score: float = 0.0


@dataclass
class GeneratedPost:
    topic: str
    hook: str
    body: str
    cta: str
    hashtags: list[str]
    image_query: str
    full_text: str
    word_count: int
    post_type: str = "image"  # "image" | "carousel_script"


@dataclass
class PollContent:
    intro_text: str
    question: str
    options: list[str]
    hashtags: list[str] = field(default_factory=list)


@dataclass
class FetchedImage:
    file_path: str
    source_url: str
    photographer: str
    alt_text: str


@dataclass
class PublishResult:
    success: bool
    post_id: str | None = None
    post_url: str | None = None
    error: str | None = None


# Sentinel prefixes used to signal an in-flight command from the approval UI
# back to the running pipeline (e.g. user typed /newtopic during selection).
NEWTOPIC_PREFIX = "__NEWTOPIC__:"
URL_PREFIX = "__URL__:"


@dataclass
class VersionSelection:
    """Result of asking the user to pick one of N generated versions."""

    selected_post: GeneratedPost | None = None
    edited_text: str | None = None       # raw /edit text, or a sentinel command
    user_image_path: str | None = None   # photo the user uploaded, if any

    @property
    def skipped(self) -> bool:
        return self.selected_post is None and self.edited_text is None

    @property
    def newtopic(self) -> str | None:
        if self.edited_text and self.edited_text.startswith(NEWTOPIC_PREFIX):
            return self.edited_text[len(NEWTOPIC_PREFIX):]
        return None

    @property
    def url(self) -> str | None:
        if self.edited_text and self.edited_text.startswith(URL_PREFIX):
            return self.edited_text[len(URL_PREFIX):]
        return None
