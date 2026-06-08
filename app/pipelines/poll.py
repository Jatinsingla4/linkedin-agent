"""LinkedIn poll pipeline (Sundays). Falls back to a regular post on failure."""

from __future__ import annotations

import logging

from app import strings
from app.core import scheduler
from app.models import Topic
from app.pipelines.base import BasePipeline
from app.pipelines.regular import RegularPipeline

logger = logging.getLogger(__name__)


class PollPipeline(BasePipeline):
    async def run(self, topic: Topic, article_url: str | None = None) -> None:
        logger.info("Generating poll for: %s", topic.title[:60])
        try:
            poll = await self.s.writer.generate_poll(topic)
        except Exception as e:
            logger.error("Poll generation failed: %s — running regular post instead", e)
            await RegularPipeline(self.s).run(topic)
            return

        approved = await self.s.approval_bot.request_poll_approval(
            intro_text=poll.intro_text, question=poll.question, options=poll.options, topic=topic.title
        )
        if not approved:
            await self.s.approval_bot.send_notification(strings.SKIPPED_POLL)
            return

        await scheduler.wait_for_ideal_time(notify=self.s.approval_bot.send_notification)
        result = await self.s.publisher.publish_poll(
            poll.intro_text, poll.question, poll.options, poll.hashtags
        )
        if result.success:
            self.s.state.mark_topic_used(topic.title)
            self.s.state.record_published(topic.title, result.post_url)
            await self.s.approval_bot.send_notification(strings.poll_published(result.post_url))
        else:
            await self.s.approval_bot.send_notification(strings.publish_failed(result.error))
