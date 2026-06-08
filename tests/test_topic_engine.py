"""TopicEngine: scoring, dedup, cleaning, fallback."""

from __future__ import annotations

from app.models import Topic
from app.services.topic_engine import TopicEngine


def engine() -> TopicEngine:
    return TopicEngine(["marketing", "ai", "branding"])


def test_relevance_score_keywords_and_source():
    e = engine()
    rss = Topic(title="AI in marketing is changing branding", source="rss")
    reddit = Topic(title="Some unrelated cooking recipe thread", source="reddit/r/food")
    assert e._relevance_score(rss) == 2.0 * 3 + 1.0  # 3 keywords + rss bonus
    assert e._relevance_score(reddit) == 0.0


def test_short_title_penalised():
    e = engine()
    assert e._relevance_score(Topic(title="AI", source="reddit/r/x")) == 2.0 - 1.0


def test_dedup_and_sort_by_score():
    e = engine()
    topics = [
        Topic(title="Generic thread about something here", source="reddit/r/x"),
        Topic(title="AI marketing branding insight piece", source="rss"),
        Topic(title="AI marketing branding insight piece", source="rss"),  # dup
    ]
    result = e._score_and_deduplicate(topics)
    assert len(result) == 2
    assert "AI marketing" in result[0].title  # highest score first


def test_clean_strips_cdata_and_tags():
    assert TopicEngine._clean("<![CDATA[<b>Hi</b>   there]]>") == "Hi there"


def test_fallback_returns_requested_count():
    fallback = engine()._fallback_topics(5)
    assert len(fallback) == 5
    assert all(t.source == "fallback" for t in fallback)
