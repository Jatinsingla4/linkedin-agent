"""Single owner of ``agent_state.json``.

Replaces the three duplicated ``_load_state``/``_save_state`` blocks. Writes are
atomic (temp file + ``os.replace``) so an interrupted run cannot corrupt the
state file. All mutation helpers persist immediately.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STATE: dict[str, Any] = {
    "used_topics": [],
    "posts_published": 0,
    "posts_this_week": 0,
    "recent_posts": [],
    "content_queue": [],
}

MAX_USED_TOPICS = 50
MAX_RECENT_POSTS = 10


class StateStore:
    """Load, mutate and atomically persist the agent's JSON state."""

    def __init__(self, path: str | Path = "agent_state.json"):
        self.path = Path(path)
        self._data = self._load()

    # ── Persistence ──────────────────────────────────────────
    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return {**copy.deepcopy(DEFAULT_STATE), **data}
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("State load failed (%s) — starting fresh", e)
        return copy.deepcopy(DEFAULT_STATE)

    def save(self) -> None:
        try:
            fd, tmp = tempfile.mkstemp(
                dir=self.path.parent or ".", prefix=".state_", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as e:
            logger.warning("State save failed: %s", e)

    # ── Generic access ───────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    # ── Content queue ────────────────────────────────────────
    def pop_queued_topic(self) -> str | None:
        queue: list[str] = self._data.get("content_queue", [])
        if not queue:
            return None
        title = queue.pop(0)
        self._data["content_queue"] = queue
        self.save()
        return title

    def extend_queue(self, topics: list[str]) -> None:
        self._data["content_queue"] = self._data.get("content_queue", []) + topics
        self.save()

    # ── Used topics (dedupe) ─────────────────────────────────
    def is_topic_used(self, title: str) -> bool:
        return title.lower() in set(self._data.get("used_topics", []))

    def mark_topic_used(self, title: str) -> None:
        used: list[str] = self._data.setdefault("used_topics", [])
        used.append(title.lower())
        self._data["used_topics"] = used[-MAX_USED_TOPICS:]
        self.save()

    def reset_used_topics(self) -> None:
        self._data["used_topics"] = []
        self.save()

    # ── Post bookkeeping ─────────────────────────────────────
    def record_published(self, topic: str, url: str | None) -> None:
        now = datetime.now(UTC).isoformat()
        self._data["posts_published"] = self._data.get("posts_published", 0) + 1
        self._data["posts_this_week"] = self._data.get("posts_this_week", 0) + 1
        self._data["last_post_at"] = now
        recent: list[dict] = self._data.setdefault("recent_posts", [])
        recent.append(
            {
                "topic": topic[:100],
                "url": url or "",
                "published_at": now,
                "reminder_sent": False,
            }
        )
        self._data["recent_posts"] = recent[-MAX_RECENT_POSTS:]
        self.save()
