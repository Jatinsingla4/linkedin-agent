"""PDF carousel pipeline (Saturdays). Falls back to a regular post on failure."""

from __future__ import annotations

import logging
from pathlib import Path

from app import strings
from app.core import scheduler
from app.models import Topic
from app.pipelines.base import BasePipeline
from app.pipelines.regular import RegularPipeline
from app.services.pdf_generator import create_carousel_pdf

logger = logging.getLogger(__name__)


class CarouselPipeline(BasePipeline):
    async def run(self, topic: Topic, article_url: str | None = None) -> None:
        logger.info("Generating carousel for: %s", topic.title[:60])
        pdf_path: str | None = None
        try:
            slides = await self.s.writer.generate_carousel_slides(topic)
            pdf_path = create_carousel_pdf(slides, follow_name=self.settings.your_name)

            titles = "\n".join(f"  Slide {s['slide']}: {s['title']}" for s in slides)
            await self.s.approval_bot.send_notification(
                f"📊 *Carousel Preview*\n{strings.DIVIDER}\n"
                f"📌 Topic: _{topic.title[:80]}_\n\n{titles}"
            )

            if not await self.s.approval_bot.request_poll_approval(
                intro_text=slides[0]["title"],
                question="Post this carousel?",
                options=[s["title"] for s in slides[1:5]],
                topic=f"[CAROUSEL] {topic.title}",
            ):
                await self.s.approval_bot.send_notification(strings.SKIPPED_CAROUSEL)
                return

            caption = (
                f"{slides[0]['title']}\n\n"
                + "\n".join(f"Slide {s['slide']}: {s['title']}" for s in slides[1:])
                + f"\n\nFollow for weekly insights on {', '.join(self.settings.your_niche[:3])}."
            )

            await scheduler.wait_for_ideal_time(notify=self.s.approval_bot.send_notification)
            result = await self.s.publisher.publish_document(caption, pdf_path, topic.title)
            if result.success:
                self.s.state.mark_topic_used(topic.title)
                self.s.state.record_published(topic.title, result.post_url)
                await self.s.approval_bot.send_notification(strings.carousel_published(result.post_url))
            else:
                await self.s.approval_bot.send_notification(strings.publish_failed(result.error))
        except Exception as e:
            logger.error("Carousel pipeline error: %s — falling back to regular post", e)
            await RegularPipeline(self.s).run(topic)
        finally:
            if pdf_path and Path(pdf_path).exists():
                Path(pdf_path).unlink(missing_ok=True)
