"""StateStore: persistence, recovery, and bookkeeping caps."""

from __future__ import annotations

import json

from app.core.state import MAX_RECENT_POSTS, MAX_USED_TOPICS, StateStore


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.set("posts_published", 7)
    assert StateStore(path).get("posts_published") == 7


def test_corrupt_file_recovers(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not valid json")
    store = StateStore(path)
    assert store.get("used_topics") == []  # falls back to defaults


def test_used_topics_capped(tmp_path):
    store = StateStore(tmp_path / "s.json")
    for i in range(MAX_USED_TOPICS + 20):
        store.mark_topic_used(f"topic {i}")
    assert len(store.get("used_topics")) == MAX_USED_TOPICS
    assert store.is_topic_used("TOPIC 69")  # case-insensitive


def test_recent_posts_capped(tmp_path):
    store = StateStore(tmp_path / "s.json")
    for i in range(MAX_RECENT_POSTS + 5):
        store.record_published(f"topic {i}", f"http://x/{i}")
    assert len(store.get("recent_posts")) == MAX_RECENT_POSTS
    assert store.get("posts_published") == MAX_RECENT_POSTS + 5


def test_queue_fifo(tmp_path):
    store = StateStore(tmp_path / "s.json")
    store.extend_queue(["a", "b", "c"])
    assert store.pop_queued_topic() == "a"
    assert store.get("content_queue") == ["b", "c"]


def test_atomic_write_produces_valid_json(tmp_path):
    path = tmp_path / "s.json"
    store = StateStore(path)
    store.record_published("hello", "http://x")
    assert json.loads(path.read_text())["recent_posts"][0]["topic"] == "hello"
