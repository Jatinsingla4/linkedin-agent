"""
orchestrator.py — The main pipeline runner.

Called by:
  - GitHub Actions (scheduled cron)
  - Manual: python orchestrator.py

Pipeline:
  1. Sunday: send weekly analytics report
  2. Check Telegram for /topic suggestion
  3. Fetch trending topics (or use suggestion)
  4. Pick best topic (avoids repeats)
  5. Generate 2 post versions with Gemini
  6. Fetch image (Unsplash)
  7. Send versions to Telegram — user picks one
  8. Publish to LinkedIn
  9. Auto-post first comment (2 min later)
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

# ── Logging setup ─────────────────────────────────────────────────────────────
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
        logger.info("=" * 60)
        logger.info("🚀 LinkedIn Agent pipeline started")
        logger.info(f"   User: {config.your_name} @ {config.your_company}")
        logger.info("=" * 60)

        await self.approval_bot.send_notification(
            f"🤖 *LinkedIn Agent Starting*\n"
            f"Fetching today's topics for you, {config.your_name}..."
        )

        # Sunday weekly report
        await self._maybe_send_weekly_report()

        image_path: Optional[str] = None

        try:
            # ── Step 1: Check Telegram for /topic suggestion ──────────────
            logger.info("Checking Telegram for /topic suggestion...")
            topic_suggestion = await self.approval_bot.get_topic_suggestion()

            # ── Step 2: Fetch or use suggested topic ──────────────────────
            if topic_suggestion:
                logger.info(f"Using Telegram suggestion: {topic_suggestion}")
                topics = [Topic(title=topic_suggestion, source="telegram", relevance_score=10.0)]
                await self.approval_bot.send_notification(
                    f"📌 Using your suggested topic:\n_{topic_suggestion}_"
                )
            else:
                logger.info("Step 1/6: Fetching topics...")
                topics = await self.topic_engine.get_topics(count=15)

            # ── Step 3: Pick topic ─────────────────────────────────────────
            logger.info("Selecting best topic...")
            topic = self._pick_topic(topics)
            logger.info(f"  Selected: {topic.title}")

            # ── Step 4: Generate post versions ────────────────────────────
            versions = config.generate_versions
            logger.info(f"Generating {versions} post version(s)...")
            if versions > 1:
                posts = await self.content_writer.generate_multiple_posts(topic, count=versions)
                logger.info(f"  Generated {len(posts)} versions")
            else:
                post = await self.content_writer.generate_post(topic)
                posts = [post]
                logger.info(f"  Generated post ({post.word_count} words | type: {post.post_type})")

            # ── Step 5: Fetch image ────────────────────────────────────────
            logger.info(f"Fetching image (query: '{posts[0].image_query}')...")
            fetched_image = await self.image_fetcher.fetch_image(posts[0].image_query)
            image_path = fetched_image.file_path if fetched_image else None
            if image_path:
                logger.info(f"  Image ready: {image_path}")
            else:
                logger.warning("  No image — will post text-only")

            # ── Step 6: Version selection (always use version UI) ─────────
            logger.info(f"Sending {len(posts)} version(s) to Telegram for selection...")
            selected_post, edited_text = await self.approval_bot.request_version_selection(
                posts=posts,
                topic=topic.title,
                image_path=image_path,
            )
            if selected_post is None:
                logger.info("Post skipped — pipeline complete")
                await self.approval_bot.send_notification(
                    "📭 Skipped. I'll generate fresh versions next time!"
                )
                return
            final_text = edited_text if edited_text else selected_post.full_text

            # ── Step 7: Publish ────────────────────────────────────────────
            logger.info("Publishing to LinkedIn...")
            result = await self.publisher.publish(
                text=final_text,
                image_path=image_path,
            )

            if result.success:
                logger.info(f"✅ Post published! URL: {result.post_url}")
                self._mark_topic_used(topic)
                self._state["posts_published"] = self._state.get("posts_published", 0) + 1
                self._state["posts_this_week"] = self._state.get("posts_this_week", 0) + 1
                self._state["last_post_at"] = datetime.now(timezone.utc).isoformat()
                self._save_state()

                await self.approval_bot.send_notification(
                    f"🎉 *Post published successfully!*\n"
                    f"🔗 {result.post_url or 'Check your LinkedIn feed'}\n\n"
                    f"📌 Topic: _{topic.title[:80]}_"
                )

                # ── Step 8: Auto first comment ─────────────────────────────
                if config.enable_first_comment and result.post_id:
                    await self._post_first_comment(final_text, result.post_id)

            else:
                logger.error(f"❌ Publish failed: {result.error}")
                await self.approval_bot.send_notification(
                    f"❌ *Failed to publish post*\n`{result.error}`\n\n"
                    f"Please check your LinkedIn token or publish manually."
                )

        except Exception as e:
            logger.exception(f"Pipeline error: {e}")
            await self.approval_bot.send_notification(
                f"🔥 *Agent pipeline error:*\n`{str(e)[:300]}`\n\nCheck logs."
            )
            raise

        finally:
            if image_path:
                ImageFetcher.cleanup(image_path)
            logger.info("Pipeline finished")
            logger.info("=" * 60)

    # ── First comment ─────────────────────────────────────────────────────────

    async def _post_first_comment(self, post_text: str, post_id: str) -> None:
        logger.info("First comment: waiting 2 minutes...")
        await asyncio.sleep(120)
        try:
            comment = await self.content_writer.generate_first_comment(post_text)
            success = await self.publisher.post_comment(post_id, comment)
            if success:
                logger.info(f"First comment posted: {comment[:80]}")
                await self.approval_bot.send_notification(
                    f"💬 *First comment posted!*\n_{comment[:200]}_"
                )
            else:
                logger.warning("First comment failed — skipping")
        except Exception as e:
            logger.warning(f"First comment error (non-fatal): {e}")

    # ── Weekly analytics ──────────────────────────────────────────────────────

    async def _maybe_send_weekly_report(self) -> None:
        today_str = date.today().isoformat()
        today_weekday = datetime.now(timezone.utc).weekday()  # 6 = Sunday

        if today_weekday != 6:
            return
        if self._state.get("last_weekly_report") == today_str:
            return

        posts_total = self._state.get("posts_published", 0)
        posts_this_week = self._state.get("posts_this_week", 0)
        last_post = self._state.get("last_post_at", "Never")
        last_post_display = last_post[:10] if last_post != "Never" else "Never"

        report = (
            f"📊 *Weekly LinkedIn Report*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 Posts this week: *{posts_this_week}*\n"
            f"📈 Total posts ever: *{posts_total}*\n"
            f"🕐 Last posted: *{last_post_display}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Agent running smoothly!"
        )
        await self.approval_bot.send_notification(report)
        self._state["last_weekly_report"] = today_str
        self._state["posts_this_week"] = 0
        self._save_state()
        logger.info("Weekly analytics report sent")

    # ── Topic selection ───────────────────────────────────────────────────────

    def _pick_topic(self, topics: list[Topic]) -> Topic:
        used_titles = set(self._state.get("used_topics", []))
        for topic in topics:
            if topic.title.lower() not in used_titles:
                return topic
        logger.info("All fetched topics were recently used — resetting topic history")
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
                logger.warning(f"Could not load state file: {e} — starting fresh")
        return {"used_topics": [], "posts_published": 0, "posts_this_week": 0}

    def _save_state(self) -> None:
        try:
            STATE_FILE.write_text(json.dumps(self._state, indent=2))
            logger.debug("State saved")
        except OSError as e:
            logger.warning(f"Could not save state: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    orchestrator = Orchestrator()
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
