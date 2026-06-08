"""Discovers fresh, relevant post topics from free sources.

  1. RSS feeds from marketing/tech/business publications
  2. Reddit JSON API (public, no auth)
  3. Fallback: a curated evergreen list when everything else fails
"""

from __future__ import annotations

import logging
import random
import re

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.http import create_session
from app.models import Topic

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://blog.hubspot.com/marketing/rss.xml",
    "https://contentmarketinginstitute.com/feed/",
    "https://www.convinceandconvert.com/feed/",
    "https://www.marketingweek.com/feed/",
    "https://adage.com/rss.xml",
    "https://feeds.harvardbusiness.org/harvardbusiness/",
    "https://www.fastcompany.com/latest/rss",
    "https://blog.hootsuite.com/feed/",
    "https://www.marketingaiinstitute.com/blog/rss.xml",
    "https://techcrunch.com/feed/",
    "https://venturebeat.com/feed/",
]

REDDIT_SUBREDDITS = [
    "marketing", "branding", "digitalmarketing", "advertising",
    "socialmedia", "entrepreneur", "startups", "content_marketing",
]

FALLBACK_TOPICS = [
    "Why most brand campaigns fail in the first 90 days",
    "The real difference between marketing and branding",
    "How AI is changing creative agencies in India",
    "What consumer brands do differently to build cult followings",
    "What clients really want vs what agencies think they want",
    "The underrated power of consistency in brand building",
    "Why storytelling beats specs every time in product marketing",
    "How to measure brand health beyond just sales numbers",
    "The agency-client relationship: what makes it actually work",
    "Building a personal brand when you work behind the scenes",
    "What I learned pitching 50+ campaigns to big brand clients",
    "Why most social media strategies fail for consumer brands",
    "The gap between what brands say and what consumers hear",
    "How AI tools are changing the daily life of a marketer",
    "Why brand consistency matters more than creative brilliance",
    "The one thing consumer brands always get wrong on social media",
    "What agency life teaches you that no MBA can",
    "Why the best campaigns start with a single human insight",
    "How to build a brand people talk about without being asked",
    "The truth about viral marketing: luck vs strategy",
]


class TopicEngine:
    def __init__(self, niche_keywords: list[str]):
        self.niche_keywords = [k.lower() for k in niche_keywords]

    async def get_topics(self, count: int = 10) -> list[Topic]:
        all_topics: list[Topic] = []
        async with create_session() as session:
            all_topics.extend(await self._fetch_rss_topics(session))
            all_topics.extend(await self._fetch_reddit_topics(session))

        if not all_topics:
            logger.warning("All external sources failed — using fallback topics")
            return self._fallback_topics(count)

        scored = self._score_and_deduplicate(all_topics)
        top = scored[:count]
        logger.info("TopicEngine: %d topics from %d candidates", len(top), len(all_topics))
        return top

    # ── RSS ──────────────────────────────────────────────────
    async def _fetch_rss_topics(self, session: aiohttp.ClientSession) -> list[Topic]:
        topics: list[Topic] = []
        for feed_url in RSS_FEEDS:
            try:
                topics.extend(await self._parse_rss(session, feed_url))
            except Exception as e:
                logger.debug("RSS feed failed (%s): %s", feed_url, e)
        return topics

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def _parse_rss(self, session: aiohttp.ClientSession, url: str) -> list[Topic]:
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()

        topics: list[Topic] = []
        for item in re.findall(r"<item>(.*?)</item>", text, re.DOTALL)[:5]:
            title = self._extract_tag(item, "title")
            if not title:
                continue
            summary = self._extract_tag(item, "description")
            topics.append(
                Topic(
                    title=self._clean(title),
                    summary=self._clean(summary)[:200] if summary else None,
                    url=self._extract_tag(item, "link"),
                    source="rss",
                )
            )
        return topics

    # ── Reddit ───────────────────────────────────────────────
    async def _fetch_reddit_topics(self, session: aiohttp.ClientSession) -> list[Topic]:
        topics: list[Topic] = []
        for sub in random.sample(REDDIT_SUBREDDITS, min(3, len(REDDIT_SUBREDDITS))):
            try:
                topics.extend(await self._fetch_subreddit(session, sub))
            except Exception as e:
                logger.debug("Reddit r/%s failed: %s", sub, e)
        return topics

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _fetch_subreddit(self, session: aiohttp.ClientSession, subreddit: str) -> list[Topic]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=10"
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        topics: list[Topic] = []
        for post in data.get("data", {}).get("children", []):
            p = post.get("data", {})
            if p.get("stickied") or p.get("is_video"):
                continue
            title = p.get("title", "").strip()
            if len(title) > 20:
                topics.append(
                    Topic(
                        title=title,
                        summary=p.get("selftext", "")[:200] or None,
                        url=f"https://reddit.com{p.get('permalink', '')}",
                        source=f"reddit/r/{subreddit}",
                    )
                )
        return topics

    # ── Scoring ──────────────────────────────────────────────
    def _score_and_deduplicate(self, topics: list[Topic]) -> list[Topic]:
        seen: set[str] = set()
        unique: list[Topic] = []
        for topic in topics:
            key = topic.title.lower()[:60]
            if key in seen:
                continue
            seen.add(key)
            topic.relevance_score = self._relevance_score(topic)
            unique.append(topic)
        return sorted(unique, key=lambda t: t.relevance_score, reverse=True)

    def _relevance_score(self, topic: Topic) -> float:
        score = 0.0
        text = (topic.title + " " + (topic.summary or "")).lower()
        for keyword in self.niche_keywords:
            if keyword in text:
                score += 2.0
        if topic.source == "rss":
            score += 1.0
        if len(topic.title) < 20:
            score -= 1.0
        return score

    def _fallback_topics(self, count: int) -> list[Topic]:
        pool = list(FALLBACK_TOPICS)
        random.shuffle(pool)
        return [Topic(title=t, source="fallback", relevance_score=1.0) for t in pool[:count]]

    # ── Utilities ────────────────────────────────────────────
    @staticmethod
    def _extract_tag(text: str, tag: str) -> str | None:
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"\s+", " ", text).strip()
