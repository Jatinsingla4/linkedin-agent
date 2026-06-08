"""Personal story pipeline: vulnerable, first-person posts.

Fixes the original crash where image fetching referenced an undefined ``post``
variable instead of the generated list.
"""

from __future__ import annotations

import logging

from app import strings
from app.models import Topic
from app.pipelines.base import BasePipeline
from app.pipelines.regular import RegularPipeline
from app.services.image_fetcher import ImageFetcher

logger = logging.getLogger(__name__)


class StoryPipeline(BasePipeline):
    async def run(self, topic: Topic, article_url: str | None = None) -> None:
        temp_images: list[str | None] = []
        try:
            posts = await self.s.writer.generate_stories(
                topic, count=self.settings.generate_versions
            )
            # FIX: fetch image from the first generated post (was an undefined `post`).
            fetched = await self.s.image_fetcher.fetch_image(posts[0].image_query)
            image_path = fetched.file_path if fetched else None
            temp_images.append(image_path)

            selection = await self.s.approval_bot.request_version_selection(
                posts=posts, topic=f"[STORY] {topic.title}", image_path=image_path
            )
            temp_images.append(selection.user_image_path)

            if selection.skipped:
                await self.s.approval_bot.send_notification(strings.SKIPPED_STORY)
                return

            # Live commands reuse the regular pipeline's behaviour.
            if selection.newtopic:
                await RegularPipeline(self.s).run(
                    Topic(title=selection.newtopic, source="telegram", relevance_score=10.0)
                )
                return
            if selection.url:
                article_text = await self.fetch_article_text(selection.url)
                post = await self.s.writer.generate_post_from_article(selection.url, article_text)
                await self.publish_and_record(
                    post.full_text, selection.user_image_path or image_path, topic
                )
                return

            text = selection.edited_text or (
                selection.selected_post.full_text if selection.selected_post else ""
            )
            await self.publish_and_record(text, selection.user_image_path or image_path, topic)
        finally:
            for path in temp_images:
                ImageFetcher.cleanup(path)
