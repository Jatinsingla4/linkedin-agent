"""Top-level coordinator.

Wires up services, resolves the topic, picks the pipeline for today, and runs it.
All heavy lifting lives in the services/pipelines; this stays thin.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime

from app import strings
from app.config import Settings
from app.config import settings as default_settings
from app.core import scheduler
from app.core.state import StateStore
from app.models import PostType, Topic
from app.pipelines.base import Services
from app.pipelines.carousel import CarouselPipeline
from app.pipelines.poll import PollPipeline
from app.pipelines.regular import RegularPipeline
from app.pipelines.story import StoryPipeline
from app.reporting import Reporting
from app.services.content.writer import ContentWriter
from app.services.gemini_client import GeminiClient
from app.services.image_fetcher import ImageFetcher
from app.services.linkedin.publisher import LinkedInPublisher
from app.services.telegram_bot import ApprovalBot
from app.services.topic_engine import TopicEngine

logger = logging.getLogger(__name__)

PRE_RUN_WINDOW_SECONDS = 30
TOPIC_POOL_SIZE = 5

PIPELINES = {
    PostType.REGULAR: RegularPipeline,
    PostType.STORY: StoryPipeline,
    PostType.POLL: PollPipeline,
    PostType.CAROUSEL: CarouselPipeline,
}


class Orchestrator:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or default_settings
        gemini = GeminiClient(self.settings)
        writer = ContentWriter(self.settings, gemini)
        self.topic_engine = TopicEngine(self.settings.your_niche)
        self.approval_bot = ApprovalBot(self.settings, content_writer=writer)
        self.state = StateStore()
        self.reporting = Reporting(self.state, self.approval_bot)
        self.services = Services(
            settings=self.settings,
            writer=writer,
            image_fetcher=ImageFetcher(self.settings),
            approval_bot=self.approval_bot,
            publisher=LinkedInPublisher(self.settings),
            state=self.state,
        )

    async def run(self) -> None:
        weekday = datetime.now(UTC).weekday()
        post_type = scheduler.post_type_for_day(weekday, self.settings)

        logger.info("=" * 60)
        logger.info(
            "🚀 LinkedIn Agent | %s post | %s @ %s",
            post_type.value.upper(), self.settings.your_name, self.settings.your_company,
        )
        logger.info("=" * 60)

        await self.approval_bot.send_notification(strings.agent_starting(post_type.value))
        await asyncio.sleep(PRE_RUN_WINDOW_SECONDS)

        await self.reporting.maybe_send_weekly_report()
        await self.reporting.send_performance_reminders()

        try:
            topic, article_url = await self._resolve_topic()
            pipeline = PIPELINES[post_type](self.services)
            await pipeline.run(topic, article_url)
        except Exception as e:
            logger.exception("Pipeline error: %s", e)
            await self.approval_bot.send_notification(strings.pipeline_error(str(e)))
            raise

    # ── Topic resolution ─────────────────────────────────────
    async def _resolve_topic(self) -> tuple[Topic, str | None]:
        url = await self.approval_bot.get_url_suggestion()
        if url:
            await self.approval_bot.send_notification(strings.using_url(url))
            return Topic(title=f"Article: {url[:60]}", source="url", relevance_score=10.0), url

        suggestion = await self.approval_bot.get_topic_suggestion()
        if suggestion:
            await self.approval_bot.send_notification(strings.using_topic(suggestion))
            return Topic(title=suggestion, source="telegram", relevance_score=10.0), None

        queued = self.state.pop_queued_topic()
        if queued:
            logger.info("Using queued topic: %s", queued)
            await self.approval_bot.send_notification(strings.using_queued_topic(queued))
            return Topic(title=queued, source="calendar", relevance_score=9.0), None

        topics = await self.topic_engine.get_topics(count=25)
        return self._pick_topic(topics), None

    def _pick_topic(self, topics: list[Topic]) -> Topic:
        unused = [t for t in topics if not self.state.is_topic_used(t.title)]
        if not unused:
            self.state.reset_used_topics()
            unused = topics
        return random.choice(unused[:TOPIC_POOL_SIZE])
