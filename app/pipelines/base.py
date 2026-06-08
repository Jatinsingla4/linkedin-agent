"""Shared pipeline scaffolding.

Holds the services every pipeline needs and the steps they all repeat:
publishing + state bookkeeping + notification, the first-comment flow, ideal-time
waiting, and article fetching. Subclasses implement :meth:`run`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from app import strings
from app.config import Settings
from app.core import scheduler
from app.core.http import create_session
from app.core.state import StateStore
from app.models import Topic
from app.services.content.writer import ContentWriter
from app.services.image_fetcher import ImageFetcher
from app.services.linkedin.publisher import LinkedInPublisher
from app.services.telegram_bot import ApprovalBot

logger = logging.getLogger(__name__)

FIRST_COMMENT_DELAY_SECONDS = 120
ARTICLE_FETCH_LIMIT = 3000


@dataclass
class Services:
    """Bundle of shared dependencies injected into every pipeline."""

    settings: Settings
    writer: ContentWriter
    image_fetcher: ImageFetcher
    approval_bot: ApprovalBot
    publisher: LinkedInPublisher
    state: StateStore


class BasePipeline:
    def __init__(self, services: Services):
        self.s = services

    @property
    def settings(self) -> Settings:
        return self.s.settings

    async def run(self, topic: Topic, article_url: str | None = None) -> None:  # pragma: no cover
        raise NotImplementedError

    # ── Publish + record + notify (shared by all pipelines) ──
    async def publish_and_record(self, text: str, image_path: str | None, topic: Topic) -> None:
        await scheduler.wait_for_ideal_time(notify=self.s.approval_bot.send_notification)
        result = await self.s.publisher.publish(text=text, image_path=image_path)
        if not result.success:
            await self.s.approval_bot.send_notification(strings.publish_failed(result.error))
            return

        self.s.state.mark_topic_used(topic.title)
        self.s.state.record_published(topic.title, result.post_url)
        await self.s.approval_bot.send_notification(strings.published(topic.title, result.post_url))

        if self.settings.enable_first_comment and result.post_id:
            await self._post_first_comment(text, result.post_id)

    async def _post_first_comment(self, post_text: str, post_id: str) -> None:
        logger.info("First comment: waiting %ds...", FIRST_COMMENT_DELAY_SECONDS)
        await asyncio.sleep(FIRST_COMMENT_DELAY_SECONDS)
        try:
            comment = await self.s.writer.generate_first_comment(post_text)
            if await self.s.publisher.post_comment(post_id, comment):
                await self.s.approval_bot.send_notification(strings.first_comment_posted(comment))
        except Exception as e:
            logger.warning("First comment error (non-fatal): %s", e)

    # ── Article fetching ─────────────────────────────────────
    async def fetch_article_text(self, url: str) -> str:
        try:
            async with create_session() as session:
                async with session.get(url) as resp:
                    html = await resp.text()
            html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
            logger.info("Fetched article (%d chars): %s", len(text), url[:60])
            return text[:ARTICLE_FETCH_LIMIT]
        except Exception as e:
            logger.warning("Article fetch failed: %s", e)
            return ""
