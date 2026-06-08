"""Regular post pipeline: N versions, user picks one (with live edit commands)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app import strings
from app.models import Topic, VersionSelection
from app.pipelines.base import BasePipeline
from app.services.image_fetcher import ImageFetcher

logger = logging.getLogger(__name__)


@dataclass
class Resolution:
    """A publishable result derived from a user's selection."""

    text: str
    topic: Topic
    image_path: str | None


class RegularPipeline(BasePipeline):
    async def run(self, topic: Topic, article_url: str | None = None) -> None:
        temp_images: list[str | None] = []
        try:
            posts = await self._generate(topic, article_url)
            fetched = await self.s.image_fetcher.fetch_image(posts[0].image_query)
            image_path = fetched.file_path if fetched else None
            temp_images.append(image_path)

            selection = await self.s.approval_bot.request_version_selection(
                posts=posts, topic=topic.title, image_path=image_path
            )
            temp_images.append(selection.user_image_path)

            resolution = await self._resolve(selection, topic, image_path, temp_images)
            if resolution is None:
                await self.s.approval_bot.send_notification(strings.SKIPPED)
                return

            await self.publish_and_record(resolution.text, resolution.image_path, resolution.topic)
        finally:
            for path in temp_images:
                ImageFetcher.cleanup(path)

    async def _generate(self, topic: Topic, article_url: str | None):
        if article_url:
            article_text = await self.fetch_article_text(article_url)
            return [await self.s.writer.generate_post_from_article(article_url, article_text)]
        return await self.s.writer.generate_multiple_posts(
            topic, count=self.settings.generate_versions
        )

    async def _resolve(
        self,
        selection: VersionSelection,
        topic: Topic,
        image_path: str | None,
        temp_images: list[str | None],
    ) -> Resolution | None:
        """Turn a user selection into a publishable Resolution, handling live commands."""
        if selection.skipped:
            return None

        # User asked for a brand-new topic — regenerate and re-select once.
        if selection.newtopic:
            new_topic = Topic(title=selection.newtopic, source="telegram", relevance_score=10.0)
            posts = await self.s.writer.generate_multiple_posts(
                new_topic, count=self.settings.generate_versions
            )
            fetched = await self.s.image_fetcher.fetch_image(posts[0].image_query)
            new_image = fetched.file_path if fetched else image_path
            temp_images.append(new_image)
            sub = await self.s.approval_bot.request_version_selection(
                posts=posts, topic=new_topic.title, image_path=new_image
            )
            temp_images.append(sub.user_image_path)
            if sub.skipped or sub.newtopic or sub.url:
                return None  # don't recurse further
            text = sub.edited_text or (sub.selected_post.full_text if sub.selected_post else "")
            return Resolution(text, new_topic, sub.user_image_path or new_image)

        # User pasted an article URL — generate from it.
        if selection.url:
            article_text = await self.fetch_article_text(selection.url)
            post = await self.s.writer.generate_post_from_article(selection.url, article_text)
            return Resolution(post.full_text, topic, selection.user_image_path or image_path)

        # Plain selection or /edit.
        text = selection.edited_text or (
            selection.selected_post.full_text if selection.selected_post else ""
        )
        return Resolution(text, topic, selection.user_image_path or image_path)
