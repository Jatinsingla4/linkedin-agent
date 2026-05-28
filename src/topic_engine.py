"""
topic_engine.py — Discovers fresh, relevant post topics.

Sources (all free, no scraping):
  1. RSS feeds from top marketing/tech/business publications
  2. Reddit JSON API (no auth needed for public feeds)
  3. Fallback: Gemini generates evergreen topics from your niche
"""

import logging
import random
import re
from datetime import datetime, timezone
from typing import List, Optional
from dataclasses import dataclass

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# ── RSS feeds — no API key needed ────────────────────────────────────────────
RSS_FEEDS = [
    # Marketing & Branding
    "https://feeds.feedburner.com/MarketingLand",
    "https://blog.hubspot.com/marketing/rss.xml",
    "https://contentmarketinginstitute.com/feed/",
    "https://www.convinceandconvert.com/feed/",
    # Business & Startups
    "https://feeds.harvardbusiness.org/harvardbusiness/",
    "https://feeds.inc.com/home/updates",
    "https://www.fastcompany.com/latest/rss",
    # AI & Tech
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
]

# ── Reddit communities relevant to your niche ────────────────────────────────
REDDIT_SUBREDDITS = [
    "marketing", "branding", "digitalmarketing",
    "startups", "entrepreneur", "socialmedia",
    "artificial", "MachineLearning",
]


@dataclass
class Topic:
    title: str
    source: str
    summary: Optional[str] = None
    url: Optional[str] = None
    relevance_score: float = 0.0


class TopicEngine:
    def __init__(self, niche_keywords: List[str]):
        self.niche_keywords = [k.lower() for k in niche_keywords]

    # ── Public interface ──────────────────────────────────────────────────────

    async def get_topics(self, count: int = 10) -> List[Topic]:
        """
        Returns a ranked list of fresh topics from multiple sources.
        Falls back gracefully if any source fails.
        """
        all_topics: List[Topic] = []

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "LinkedInAgent/1.0 (personal automation bot)"}
        ) as session:
            # Run all sources, collect whatever succeeds
            rss_topics = await self._fetch_rss_topics(session)
            reddit_topics = await self._fetch_reddit_topics(session)
            all_topics.extend(rss_topics)
            all_topics.extend(reddit_topics)

        if not all_topics:
            logger.warning("All external sources failed — using fallback topics")
            return self._fallback_topics(count)

        # Score and deduplicate
        scored = self._score_and_deduplicate(all_topics)
        top = scored[:count]
        logger.info(f"TopicEngine: retrieved {len(top)} topics from {len(all_topics)} candidates")
        return top

    # ── RSS fetching ──────────────────────────────────────────────────────────

    async def _fetch_rss_topics(self, session: aiohttp.ClientSession) -> List[Topic]:
        topics = []
        for feed_url in RSS_FEEDS:
            try:
                topics.extend(await self._parse_rss(session, feed_url))
            except Exception as e:
                logger.debug(f"RSS feed failed ({feed_url}): {e}")
        return topics

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def _parse_rss(self, session: aiohttp.ClientSession, url: str) -> List[Topic]:
        async with session.get(url, ssl=False) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()

        topics = []
        # Lightweight XML parsing without lxml dependency
        items = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
        for item in items[:5]:  # Top 5 per feed
            title = self._extract_xml_tag(item, "title")
            summary = self._extract_xml_tag(item, "description")
            link = self._extract_xml_tag(item, "link")
            if title:
                topics.append(Topic(
                    title=self._clean_text(title),
                    summary=self._clean_text(summary)[:200] if summary else None,
                    url=link,
                    source="rss"
                ))
        return topics

    # ── Reddit fetching ───────────────────────────────────────────────────────

    async def _fetch_reddit_topics(self, session: aiohttp.ClientSession) -> List[Topic]:
        topics = []
        # Pick 3 random subreddits to avoid hammering Reddit
        chosen = random.sample(REDDIT_SUBREDDITS, min(3, len(REDDIT_SUBREDDITS)))
        for sub in chosen:
            try:
                topics.extend(await self._fetch_subreddit(session, sub))
            except Exception as e:
                logger.debug(f"Reddit r/{sub} failed: {e}")
        return topics

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _fetch_subreddit(self, session: aiohttp.ClientSession, subreddit: str) -> List[Topic]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=10"
        async with session.get(url, ssl=False) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        topics = []
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            if p.get("stickied") or p.get("is_video"):
                continue
            title = p.get("title", "").strip()
            if len(title) > 20:  # Filter out noise
                topics.append(Topic(
                    title=title,
                    summary=p.get("selftext", "")[:200] or None,
                    url=f"https://reddit.com{p.get('permalink', '')}",
                    source=f"reddit/r/{subreddit}"
                ))
        return topics

    # ── Scoring & deduplication ───────────────────────────────────────────────

    def _score_and_deduplicate(self, topics: List[Topic]) -> List[Topic]:
        seen_titles: set = set()
        unique: List[Topic] = []

        for topic in topics:
            normalized = topic.title.lower()[:60]
            if normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            topic.relevance_score = self._relevance_score(topic)
            unique.append(topic)

        return sorted(unique, key=lambda t: t.relevance_score, reverse=True)

    def _relevance_score(self, topic: Topic) -> float:
        score = 0.0
        text = (topic.title + " " + (topic.summary or "")).lower()

        # Keyword matching
        for keyword in self.niche_keywords:
            if keyword in text:
                score += 2.0

        # Freshness bonus for RSS (assumed recent)
        if topic.source == "rss":
            score += 1.0

        # Penalise overly short or clickbait titles
        if len(topic.title) < 20:
            score -= 1.0

        return score

    # ── Fallback ─────────────────────────────────────────────────────────────

    def _fallback_topics(self, count: int) -> List[Topic]:
        """Evergreen topics that always work for marketing/brand professionals."""
        evergreen = [
            "Why most brand campaigns fail in the first 90 days",
            "The real difference between marketing and branding",
            "How AI is changing creative agencies in 2025",
            "5 lessons from FMCG brands that built cult followings",
            "What clients really want vs what agencies think they want",
            "The underrated power of consistency in brand building",
            "Why storytelling beats specs every time in product marketing",
            "How to measure brand health beyond just sales numbers",
            "The agency-client relationship: what makes it actually work",
            "Building a personal brand when you work behind the scenes",
        ]
        random.shuffle(evergreen)
        return [
            Topic(title=t, source="fallback", relevance_score=1.0)
            for t in evergreen[:count]
        ]

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_xml_tag(text: str, tag: str) -> Optional[str]:
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else None

    @staticmethod
    def _clean_text(text: str) -> str:
        # Strip CDATA, HTML tags, and extra whitespace
        text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
