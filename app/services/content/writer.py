"""ContentWriter — turns topics into structured posts.

Builds prompts (from :mod:`prompts`), runs them through :class:`GeminiClient`,
and parses/validates the results into :class:`GeneratedPost` / :class:`PollContent`.
"""

from __future__ import annotations

import asyncio
import logging
import random

from app.config import Settings
from app.models import GeneratedPost, PollContent, Topic
from app.services.content import prompts
from app.services.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Spacing between sequential generations to stay within rate limits.
RATE_LIMIT_GAP_SECONDS = 35

REQUIRED_FIELDS = ["hook", "body", "cta", "hashtags", "image_query"]


class ContentWriter:
    def __init__(self, settings: Settings, gemini: GeminiClient):
        self._settings = settings
        self._gemini = gemini

    # ── Regular posts ────────────────────────────────────────
    async def generate_post(
        self, topic: Topic, post_format: dict[str, str] | None = None
    ) -> GeneratedPost:
        fmt = post_format or random.choice(prompts.POST_FORMATS)
        logger.info("ContentWriter: format '%s' for: %s", fmt["name"], topic.title[:60])
        prompt = prompts.regular_post_prompt(self._settings, topic, fmt)
        data = await self._gemini.generate_json(prompt)
        return self._parse_post(data, topic)

    async def generate_multiple_posts(self, topic: Topic, count: int = 2) -> list[GeneratedPost]:
        """Generate N variations, each with a *different* format."""
        formats = random.sample(prompts.POST_FORMATS, k=min(count, len(prompts.POST_FORMATS)))
        posts: list[GeneratedPost] = []
        for i, fmt in enumerate(formats):
            if i > 0:
                await asyncio.sleep(RATE_LIMIT_GAP_SECONDS)
            try:
                posts.append(await self.generate_post(topic, post_format=fmt))
            except Exception as e:
                logger.warning("Version %d generation failed: %s", i + 1, e)
        if not posts:
            raise ValueError("All post generation attempts failed")
        return posts

    # ── Personal story ───────────────────────────────────────
    async def generate_personal_story(self, topic: Topic) -> GeneratedPost:
        prompt = prompts.personal_story_prompt(self._settings, topic)
        data = await self._gemini.generate_json(prompt, temperature=0.9)
        return self._parse_post(data, topic)

    async def generate_stories(self, topic: Topic, count: int = 2) -> list[GeneratedPost]:
        posts: list[GeneratedPost] = []
        for i in range(count):
            if i > 0:
                await asyncio.sleep(RATE_LIMIT_GAP_SECONDS)
            try:
                posts.append(await self.generate_personal_story(topic))
            except Exception as e:
                logger.warning("Story version %d failed: %s", i + 1, e)
        if not posts:
            raise ValueError("All story generation attempts failed")
        return posts

    # ── Poll ─────────────────────────────────────────────────
    async def generate_poll(self, topic: Topic) -> PollContent:
        prompt = prompts.poll_prompt(self._settings, topic)
        data = await self._gemini.generate_json(prompt, max_tokens=500)
        return PollContent(
            intro_text=data.get("intro_text", ""),
            question=data.get("question", ""),
            options=list(data.get("options", []))[:4],
            hashtags=list(data.get("hashtags", [])),
        )

    # ── Carousel ─────────────────────────────────────────────
    async def generate_carousel_slides(self, topic: Topic) -> list[dict]:
        prompt = prompts.carousel_prompt(self._settings, topic)
        data = await self._gemini.generate_json(prompt, temperature=0.8, max_tokens=1500)
        if not isinstance(data, list):
            raise ValueError("Carousel response was not a JSON array")
        return data

    # ── Calendar ─────────────────────────────────────────────
    async def generate_weekly_topics(self, count: int = 4) -> list[str]:
        prompt = prompts.weekly_topics_prompt(self._settings, count)
        data = await self._gemini.generate_json(prompt, temperature=0.9, max_tokens=500)
        return [str(t) for t in data]

    # ── Article-based ────────────────────────────────────────
    async def generate_post_from_article(self, url: str, article_text: str) -> GeneratedPost:
        prompt = prompts.article_post_prompt(self._settings, url, article_text)
        data = await self._gemini.generate_json(prompt)
        topic = Topic(title=f"Article: {url[:60]}", source="url", relevance_score=10.0)
        return self._parse_post(data, topic)

    # ── First comment & rewrite ──────────────────────────────
    async def generate_first_comment(self, post_text: str) -> str:
        prompt = prompts.first_comment_prompt(self._settings, post_text)
        return await self._gemini.generate_text(prompt, temperature=0.7, max_tokens=100)

    async def rewrite_post(self, original_text: str, instruction: str) -> str:
        prompt = prompts.rewrite_prompt(self._settings, original_text, instruction)
        return await self._gemini.generate_text(prompt)

    # ── Parsing ──────────────────────────────────────────────
    def _parse_post(self, data: dict, topic: Topic) -> GeneratedPost:
        missing = [k for k in REQUIRED_FIELDS if k not in data]
        if missing:
            raise ValueError(f"Gemini response missing fields: {missing}")

        hook = str(data["hook"]).strip()
        body = str(data["body"]).strip()
        cta = str(data["cta"]).strip()
        hashtags = [f"#{str(h).lstrip('#').lower()}" for h in data["hashtags"][:8]]
        image_query = str(data["image_query"]).strip()
        post_type = data.get("post_type", "image")

        full_text = f"{hook}\n\n{body}\n\n{cta}\n\n{' '.join(hashtags)}"
        return GeneratedPost(
            topic=topic.title,
            hook=hook,
            body=body,
            cta=cta,
            hashtags=hashtags,
            image_query=image_query,
            post_type=post_type,
            full_text=full_text,
            word_count=len(full_text.split()),
        )
