"""
orchestrator.py — Main pipeline runner.

Post type by day (IST):
  Tuesday   → Regular post (2 versions)
  Thursday  → Personal Story
  Saturday  → PDF Carousel
  Sunday    → LinkedIn Poll
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from config.settings import config
from src.topic_engine import TopicEngine, Topic
from src.content_writer import ContentWriter, GeneratedPost
from src.image_fetcher import ImageFetcher
from src.approval_bot import ApprovalBot, ApprovalStatus
from src.linkedin_publisher import LinkedInPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", mode="a"),
    ]
)
logger = logging.getLogger("orchestrator")

STATE_FILE = Path("agent_state.json")


class Orchestrator:
    def __init__(self):
        self.topic_engine = TopicEngine(niche_keywords=config.your_niche)
        self.content_writer = ContentWriter()
        self.image_fetcher = ImageFetcher()
        self.approval_bot = ApprovalBot()
        self.publisher = LinkedInPublisher()
        self._state = self._load_state()

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self) -> None:
        today = datetime.now(timezone.utc).weekday()
        post_type = self._get_post_type(today)

        logger.info("=" * 60)
        logger.info(f"🚀 LinkedIn Agent | {post_type.upper()} post | {config.your_name} @ {config.your_company}")
        logger.info("=" * 60)

        await self.approval_bot.send_notification(
            f"🤖 *LinkedIn Agent Starting*\n"
            f"Post type today: *{post_type}* 📝"
        )

        await self._maybe_send_weekly_report()
        await self.send_performance_reminders()

        try:
            # Get topic (from queue or fresh)
            topic = await self._get_topic()

            if post_type == "poll":
                await self._run_poll_pipeline(topic)
            elif post_type == "carousel":
                await self._run_carousel_pipeline(topic)
            elif post_type == "story":
                await self._run_story_pipeline(topic)
            else:
                await self._run_regular_pipeline(topic)

        except Exception as e:
            logger.exception(f"Pipeline error: {e}")
            await self.approval_bot.send_notification(
                f"🔥 *Pipeline error:*\n`{str(e)[:300]}`"
            )
            raise

    def _get_post_type(self, weekday: int) -> str:
        if weekday == config.poll_day:
            return "poll"
        if weekday == config.carousel_day:
            return "carousel"
        if weekday == config.personal_story_day:
            return "story"
        return "regular"

    # ── Topic resolution ──────────────────────────────────────────────────────

    async def _get_topic(self) -> Topic:
        # Check Telegram /topic suggestion first
        topic_suggestion = await self.approval_bot.get_topic_suggestion()
        if topic_suggestion:
            await self.approval_bot.send_notification(
                f"📌 Using your suggested topic:\n_{topic_suggestion}_"
            )
            return Topic(title=topic_suggestion, source="telegram", relevance_score=10.0)

        # Check content calendar queue
        queue = self._state.get("content_queue", [])
        if queue:
            title = queue.pop(0)
            self._state["content_queue"] = queue
            self._save_state()
            logger.info(f"Using queued topic: {title}")
            await self.approval_bot.send_notification(f"📅 Using this week's planned topic:\n_{title}_")
            return Topic(title=title, source="calendar", relevance_score=9.0)

        # Auto-fetch
        topics = await self.topic_engine.get_topics(count=15)
        return self._pick_topic(topics)

    # ── Regular pipeline ──────────────────────────────────────────────────────

    async def _run_regular_pipeline(self, topic: Topic) -> None:
        image_path: Optional[str] = None
        try:
            versions = config.generate_versions
            logger.info(f"Generating {versions} versions for: {topic.title[:60]}")
            posts = await self.content_writer.generate_multiple_posts(topic, count=versions)

            fetched = await self.image_fetcher.fetch_image(posts[0].image_query)
            image_path = fetched.file_path if fetched else None

            selected_post, edited_text = await self.approval_bot.request_version_selection(
                posts=posts, topic=topic.title, image_path=image_path
            )
            if selected_post is None:
                await self.approval_bot.send_notification("📭 Skipped. Next time!")
                return

            final_text = edited_text or selected_post.full_text
            await self._publish_and_notify(final_text, image_path, topic)
        finally:
            if image_path:
                ImageFetcher.cleanup(image_path)

    # ── Personal Story pipeline ───────────────────────────────────────────────

    async def _run_story_pipeline(self, topic: Topic) -> None:
        image_path: Optional[str] = None
        try:
            logger.info(f"Generating personal story for: {topic.title[:60]}")
            post = await self.content_writer.generate_personal_story(topic)
            posts = [post]

            fetched = await self.image_fetcher.fetch_image(post.image_query)
            image_path = fetched.file_path if fetched else None

            selected_post, edited_text = await self.approval_bot.request_version_selection(
                posts=posts, topic=f"[STORY] {topic.title}", image_path=image_path
            )
            if selected_post is None:
                await self.approval_bot.send_notification("📭 Story skipped.")
                return

            final_text = edited_text or selected_post.full_text
            await self._publish_and_notify(final_text, image_path, topic)
        finally:
            if image_path:
                ImageFetcher.cleanup(image_path)

    # ── Poll pipeline ─────────────────────────────────────────────────────────

    async def _run_poll_pipeline(self, topic: Topic) -> None:
        logger.info(f"Generating poll for: {topic.title[:60]}")
        try:
            poll_data = await self.content_writer.generate_poll(topic)
        except Exception as e:
            logger.error(f"Poll generation failed: {e} — running regular post instead")
            await self._run_regular_pipeline(topic)
            return

        intro = poll_data.get("intro_text", "")
        question = poll_data.get("question", "")
        options = poll_data.get("options", [])
        hashtags = poll_data.get("hashtags", [])

        approved = await self.approval_bot.request_poll_approval(
            intro_text=intro, question=question, options=options, topic=topic.title
        )
        if not approved:
            await self.approval_bot.send_notification("📭 Poll skipped.")
            return

        result = await self.publisher.publish_poll(intro, question, options, hashtags)
        if result.success:
            self._mark_topic_used(topic)
            self._state["posts_published"] = self._state.get("posts_published", 0) + 1
            self._state["posts_this_week"] = self._state.get("posts_this_week", 0) + 1
            self._state["last_post_at"] = datetime.now(timezone.utc).isoformat()
            self._save_recent_post(topic.title, result.post_url)
            self._save_state()
            await self.approval_bot.send_notification(
                f"🗳️ *Poll published!*\n🔗 {result.post_url or 'Check your LinkedIn feed'}"
            )
        else:
            await self.approval_bot.send_notification(f"❌ Poll failed: `{result.error}`")

    # ── Carousel pipeline ─────────────────────────────────────────────────────

    async def _run_carousel_pipeline(self, topic: Topic) -> None:
        logger.info(f"Generating carousel for: {topic.title[:60]}")
        pdf_path: Optional[str] = None
        try:
            slides = await self.content_writer.generate_carousel_slides(topic)

            from src.pdf_generator import create_carousel_pdf
            pdf_path = create_carousel_pdf(slides)
            logger.info(f"PDF created: {pdf_path}")

            # Send preview via Telegram
            titles = "\n".join(f"  Slide {s['slide']}: {s['title']}" for s in slides)
            await self.approval_bot.send_notification(
                f"📊 *Carousel Preview*\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 Topic: _{topic.title[:80]}_\n\n{titles}"
            )

            # Use version selection for final approval (reuse existing UI)
            placeholder_post = GeneratedPost(
                topic=topic.title,
                hook=slides[0]["title"],
                body="\n".join(s["content"] for s in slides[1:5]),
                cta=slides[-1].get("content", ""),
                hashtags=[],
                image_query="",
                post_type="carousel_script",
                full_text="\n\n".join(f"**{s['title']}**\n{s['content']}" for s in slides),
                word_count=200,
            )
            selected, _ = await self.approval_bot.request_version_selection(
                posts=[placeholder_post], topic=f"[CAROUSEL] {topic.title}", image_path=None
            )
            if selected is None:
                await self.approval_bot.send_notification("📭 Carousel skipped.")
                return

            caption = f"{slides[0]['title']}\n\n" + "\n".join(
                f"Slide {s['slide']}: {s['title']}" for s in slides[1:]
            ) + f"\n\nFollow for weekly insights on {', '.join(config.your_niche[:3])}."

            result = await self.publisher.publish_document(caption, pdf_path, topic.title)
            if result.success:
                self._mark_topic_used(topic)
                self._state["posts_published"] = self._state.get("posts_published", 0) + 1
                self._state["posts_this_week"] = self._state.get("posts_this_week", 0) + 1
                self._state["last_post_at"] = datetime.now(timezone.utc).isoformat()
                self._save_recent_post(topic.title, result.post_url)
                self._save_state()
                await self.approval_bot.send_notification(
                    f"📊 *Carousel published!*\n🔗 {result.post_url or 'Check your LinkedIn feed'}"
                )
            else:
                await self.approval_bot.send_notification(f"❌ Carousel failed: `{result.error}`")

        except ImportError:
            logger.error("reportlab not installed — falling back to regular post")
            await self._run_regular_pipeline(topic)
        except Exception as e:
            logger.error(f"Carousel pipeline error: {e} — falling back to regular post")
            await self._run_regular_pipeline(topic)
        finally:
            if pdf_path and Path(pdf_path).exists():
                Path(pdf_path).unlink(missing_ok=True)

    # ── Publish helper ────────────────────────────────────────────────────────

    async def _publish_and_notify(
        self, text: str, image_path: Optional[str], topic: Topic
    ) -> None:
        result = await self.publisher.publish(text=text, image_path=image_path)
        if result.success:
            self._mark_topic_used(topic)
            self._state["posts_published"] = self._state.get("posts_published", 0) + 1
            self._state["posts_this_week"] = self._state.get("posts_this_week", 0) + 1
            self._state["last_post_at"] = datetime.now(timezone.utc).isoformat()
            self._save_recent_post(topic.title, result.post_url)
            self._save_state()
            await self.approval_bot.send_notification(
                f"🎉 *Post published!*\n🔗 {result.post_url or 'Check your LinkedIn feed'}\n\n"
                f"📌 _{topic.title[:80]}_"
            )
            if config.enable_first_comment and result.post_id:
                await self._post_first_comment(text, result.post_id)
        else:
            await self.approval_bot.send_notification(f"❌ Publish failed:\n`{result.error}`")

    # ── First comment ─────────────────────────────────────────────────────────

    async def _post_first_comment(self, post_text: str, post_id: str) -> None:
        logger.info("First comment: waiting 2 minutes...")
        await asyncio.sleep(120)
        try:
            comment = await self.content_writer.generate_first_comment(post_text)
            success = await self.publisher.post_comment(post_id, comment)
            if success:
                await self.approval_bot.send_notification(
                    f"💬 *First comment posted!*\n_{comment[:200]}_"
                )
        except Exception as e:
            logger.warning(f"First comment error (non-fatal): {e}")

    # ── Performance reminders ─────────────────────────────────────────────────

    def _save_recent_post(self, topic: str, url: Optional[str]) -> None:
        recent = self._state.setdefault("recent_posts", [])
        recent.append({
            "topic": topic[:100],
            "url": url or "",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "reminder_sent": False,
        })
        self._state["recent_posts"] = recent[-10:]

    async def send_performance_reminders(self) -> None:
        recent = self._state.get("recent_posts", [])
        now = datetime.now(timezone.utc)
        updated = False
        for post in recent:
            if post.get("reminder_sent"):
                continue
            published = datetime.fromisoformat(post["published_at"])
            age_hours = (now - published).total_seconds() / 3600
            if 20 <= age_hours <= 28:
                url_line = f"🔗 {post['url']}" if post["url"] else "🔗 Check your LinkedIn feed"
                await self.approval_bot.send_notification(
                    f"📊 *Performance Check*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your post from ~24h ago:\n📌 _{post['topic'][:80]}_\n\n"
                    f"{url_line}\n\nCheck likes, comments & impressions!"
                )
                post["reminder_sent"] = True
                updated = True
        if updated:
            self._save_state()

    # ── Weekly analytics ──────────────────────────────────────────────────────

    async def _maybe_send_weekly_report(self) -> None:
        today_str = date.today().isoformat()
        if datetime.now(timezone.utc).weekday() != 6:
            return
        if self._state.get("last_weekly_report") == today_str:
            return
        posts_total = self._state.get("posts_published", 0)
        posts_this_week = self._state.get("posts_this_week", 0)
        last_post = self._state.get("last_post_at", "Never")
        await self.approval_bot.send_notification(
            f"📊 *Weekly Report*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 This week: *{posts_this_week}* posts\n"
            f"📈 Total ever: *{posts_total}* posts\n"
            f"🕐 Last posted: *{last_post[:10] if last_post != 'Never' else 'Never'}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n✅ Agent running strong!"
        )
        self._state["last_weekly_report"] = today_str
        self._state["posts_this_week"] = 0
        self._save_state()

    # ── Topic selection ───────────────────────────────────────────────────────

    def _pick_topic(self, topics: list[Topic]) -> Topic:
        used_titles = set(self._state.get("used_topics", []))
        for topic in topics:
            if topic.title.lower() not in used_titles:
                return topic
        self._state["used_topics"] = []
        return topics[0]

    def _mark_topic_used(self, topic: Topic) -> None:
        used = self._state.setdefault("used_topics", [])
        used.append(topic.title.lower())
        self._state["used_topics"] = used[-50:]

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"State load failed: {e}")
        return {"used_topics": [], "posts_published": 0, "posts_this_week": 0, "recent_posts": []}

    def _save_state(self) -> None:
        try:
            STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except OSError as e:
            logger.warning(f"State save failed: {e}")


async def main():
    orchestrator = Orchestrator()
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
