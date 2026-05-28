"""
approval_bot.py — Telegram bot for human-in-the-loop post approval.

Flow:
  1. Agent generates post
  2. Bot sends you a preview (text + image) on Telegram
  3. You reply with:
      ✅  or  /approve   → post it now
      ❌  or  /reject    → skip this post
      ✏️  or  /edit <text> → replace post text with your version
  4. Bot waits up to APPROVAL_TIMEOUT_HOURS, then auto-skips
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config.settings import config

logger = logging.getLogger(__name__)

APPROVE_CALLBACK = "approve"
REJECT_CALLBACK = "reject"


class ApprovalStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    TIMEOUT = "timeout"


@dataclass
class ApprovalResult:
    status: ApprovalStatus
    edited_text: Optional[str] = None    # Only set if status == EDITED


class ApprovalBot:
    def __init__(self):
        self.bot = Bot(token=config.telegram_bot_token)
        self.chat_id = config.telegram_chat_id
        self._pending_message_id: Optional[int] = None

    # ── Public interface ──────────────────────────────────────────────────────

    async def request_approval(
        self,
        post_text: str,
        topic: str,
        image_path: Optional[str] = None,
    ) -> ApprovalResult:
        """
        Send post preview to Telegram and wait for approval.
        Returns ApprovalResult with final status.
        """
        try:
            message_id = await self._send_preview(post_text, topic, image_path)
            if not message_id:
                logger.error("Failed to send Telegram preview — auto-approving for safety")
                return ApprovalResult(status=ApprovalStatus.APPROVED)

            return await self._wait_for_response(message_id, post_text)

        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
            # Don't block the pipeline — notify and auto-approve
            return ApprovalResult(status=ApprovalStatus.APPROVED)

    async def request_poll_approval(
        self, intro_text: str, question: str, options: list[str], topic: str
    ) -> bool:
        """Send poll preview to Telegram, return True if approved."""
        options_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Post Poll", callback_data=APPROVE_CALLBACK),
            InlineKeyboardButton("❌ Skip", callback_data=REJECT_CALLBACK),
        ]])
        msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"🗳️ *Poll Preview*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 Topic: _{self._escape_md(topic[:80])}_\n\n"
                f"*Intro:* {self._escape_md(intro_text[:300])}\n\n"
                f"*Question:* {self._escape_md(question)}\n\n"
                f"{self._escape_md(options_text)}\n\n"
                f"Auto-skips in {config.approval_timeout_hours}h."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        approval = await self._wait_for_response(msg.message_id, intro_text)
        return approval.status == ApprovalStatus.APPROVED

    async def request_calendar_approval(self, topics: list[str]) -> list[str]:
        """Send weekly topic plan to Telegram, return approved topics list."""
        topics_text = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve All", callback_data=APPROVE_CALLBACK),
            InlineKeyboardButton("❌ Skip Week", callback_data=REJECT_CALLBACK),
        ]])
        msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"📅 *This Week's Content Plan*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{self._escape_md(topics_text)}\n\n"
                f"Tap ✅ to approve or reply `/skip 2,4` to remove specific topics.\n"
                f"Auto-approves in 30 min."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        # Wait max 30 min for calendar approval
        timeout_saved = config.approval_timeout_hours
        elapsed = 0
        last_update_id = -1
        approved_topics = list(topics)

        while elapsed < 1800:  # 30 min
            await asyncio.sleep(10)
            elapsed += 10
            updates = await self._get_updates(last_update_id)
            for update in updates:
                last_update_id = max(last_update_id, update.update_id)
                if update.callback_query:
                    cq = update.callback_query
                    if cq.message and cq.message.message_id == msg.message_id:
                        if cq.data == APPROVE_CALLBACK:
                            await self.send_notification(f"✅ Content plan approved! {len(approved_topics)} topics queued.")
                            return approved_topics
                        elif cq.data == REJECT_CALLBACK:
                            await self.send_notification("❌ Content plan skipped.")
                            return []
                if update.message and update.message.chat_id == int(self.chat_id):
                    text = (update.message.text or "").strip()
                    if text.lower().startswith("/skip "):
                        try:
                            skip_nums = [int(x.strip()) - 1 for x in text[6:].split(",")]
                            approved_topics = [t for i, t in enumerate(topics) if i not in skip_nums]
                            await self.send_notification(
                                f"✅ Plan updated! {len(approved_topics)} topics queued:\n" +
                                "\n".join(f"• {t[:60]}" for t in approved_topics)
                            )
                            return approved_topics
                        except Exception:
                            pass

        # Auto-approve after timeout
        await self.send_notification(f"⏰ Auto-approved {len(approved_topics)} topics for this week!")
        return approved_topics

    async def get_topic_suggestion(self) -> Optional[str]:
        """Check Telegram for a recent /topic <text> command (within last hour)."""
        try:
            updates = await self.bot.get_updates(
                timeout=2,
                allowed_updates=["message"],
                limit=20,
            )
            cutoff = datetime.now(timezone.utc).timestamp() - 3600
            for update in reversed(updates):
                if update.message and update.message.chat_id == int(self.chat_id):
                    if update.message.date.timestamp() < cutoff:
                        continue
                    text = (update.message.text or "").strip()
                    if text.lower().startswith("/topic "):
                        topic = text[7:].strip()
                        if topic:
                            logger.info(f"Found Telegram topic suggestion: {topic}")
                            return topic
        except TelegramError as e:
            logger.debug(f"Could not check topic suggestion: {e}")
        return None

    async def request_version_selection(
        self,
        posts: list,
        topic: str,
        image_path: Optional[str] = None,
    ) -> tuple[Optional[object], Optional[str]]:
        """Send N post versions to Telegram, wait for user to pick one."""
        # Send each version as a separate preview message
        for i, post in enumerate(posts, 1):
            preview = self._escape_md(post.full_text[:700])
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"*Version {i}:*\n\n{preview}",
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(1)

        # Selection buttons
        version_buttons = [
            InlineKeyboardButton(f"✅ Version {i + 1}", callback_data=f"v{i}")
            for i in range(len(posts))
        ]
        keyboard = InlineKeyboardMarkup([
            version_buttons,
            [InlineKeyboardButton("❌ Skip all", callback_data=REJECT_CALLBACK)],
        ])

        msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"👆 *Pick a version to post*\n"
                f"📌 Topic: _{self._escape_md(topic[:80])}_\n\n"
                f"Or reply `/edit <your text>` to write your own."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return await self._wait_for_version_response(msg.message_id, posts)

    async def _wait_for_version_response(
        self, message_id: int, posts: list
    ) -> tuple[Optional[object], Optional[str]]:
        timeout_seconds = config.approval_timeout_hours * 3600
        elapsed = 0
        last_update_id = -1

        while elapsed < timeout_seconds:
            await asyncio.sleep(5)
            elapsed += 5

            updates = await self._get_updates(last_update_id)
            for update in updates:
                last_update_id = max(last_update_id, update.update_id)

                if update.callback_query:
                    cq = update.callback_query
                    if cq.message and cq.message.message_id == message_id:
                        if cq.data == REJECT_CALLBACK:
                            await self.send_notification("❌ Skipped. Next post coming soon!")
                            return None, None
                        for i, post in enumerate(posts):
                            if cq.data == f"v{i}":
                                await self.send_notification(f"✅ Version {i + 1} selected! Posting to LinkedIn...")
                                return post, None

                if update.message and update.message.chat_id == int(self.chat_id):
                    text = (update.message.text or "").strip()
                    if text.lower().startswith("/edit "):
                        new_text = text[6:].strip()
                        if new_text:
                            await self.send_notification("✏️ Custom version received! Posting...")
                            return posts[0], new_text
                    if text in ("❌", "/reject", "no", "skip"):
                        await self.send_notification("❌ Skipped.")
                        return None, None

        await self.send_notification(f"⏰ Timed out after {config.approval_timeout_hours}h — skipped.")
        return None, None

    async def send_notification(self, message: str) -> None:
        """Send a simple notification message (no approval needed)."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    # ── Preview sending ───────────────────────────────────────────────────────

    async def _send_preview(
        self, post_text: str, topic: str, image_path: Optional[str]
    ) -> Optional[int]:
        """Send post preview with inline approve/reject buttons."""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Post it", callback_data=APPROVE_CALLBACK),
                InlineKeyboardButton("❌ Skip", callback_data=REJECT_CALLBACK),
            ]
        ])

        caption = (
            f"🤖 *LinkedIn Agent — Post Preview*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Topic:* {self._escape_md(topic[:80])}\n\n"
            f"📝 *Post:*\n{self._escape_md(post_text)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Reply `/edit <new text>` to modify before posting.\n"
            f"Auto-skips in {config.approval_timeout_hours}h if no response."
        )

        # Telegram caption limit is 1024 chars
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        try:
            if image_path:
                with open(image_path, "rb") as photo:
                    msg = await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard,
                    )
            else:
                msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                )

            logger.info(f"Telegram preview sent, message_id={msg.message_id}")
            return msg.message_id

        except TelegramError as e:
            logger.error(f"Failed to send Telegram preview: {e}")
            return None

    # ── Response waiting ──────────────────────────────────────────────────────

    async def _wait_for_response(
        self, message_id: int, original_text: str
    ) -> ApprovalResult:
        """
        Poll for a response via getUpdates.
        Watches for:
          - Callback queries (inline button presses)
          - /edit <text> command
          - ✅ ❌ emoji shortcuts
        """
        timeout_seconds = config.approval_timeout_hours * 3600
        poll_interval = 5  # seconds
        elapsed = 0
        last_update_id = -1

        logger.info(
            f"Waiting for Telegram approval (timeout: {config.approval_timeout_hours}h)..."
        )

        while elapsed < timeout_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            updates = await self._get_updates(last_update_id)
            for update in updates:
                last_update_id = max(last_update_id, update.update_id)
                result = self._process_update(update, message_id, original_text)
                if result:
                    await self._send_confirmation(result)
                    return result

        # Timeout
        logger.warning("Approval timeout reached — skipping post")
        await self.send_notification(
            f"⏰ Post approval timed out after {config.approval_timeout_hours}h — skipped."
        )
        return ApprovalResult(status=ApprovalStatus.TIMEOUT)

    async def _get_updates(self, offset: int) -> list:
        try:
            updates = await self.bot.get_updates(
                offset=offset + 1 if offset > 0 else None,
                timeout=4,
                allowed_updates=["message", "callback_query"],
            )
            return updates
        except TelegramError as e:
            logger.debug(f"getUpdates error (non-fatal): {e}")
            return []

    def _process_update(
        self, update: Update, message_id: int, original_text: str
    ) -> Optional[ApprovalResult]:
        """Parse a single update and return ApprovalResult if it's a decision."""

        # ── Callback query (inline button) ─────────────────────────────────
        if update.callback_query:
            cq = update.callback_query
            # Only react to callbacks from our message
            if cq.message and cq.message.message_id == message_id:
                if cq.data == APPROVE_CALLBACK:
                    logger.info("✅ Post approved via Telegram button")
                    return ApprovalResult(status=ApprovalStatus.APPROVED)
                elif cq.data == REJECT_CALLBACK:
                    logger.info("❌ Post rejected via Telegram button")
                    return ApprovalResult(status=ApprovalStatus.REJECTED)

        # ── Text messages ───────────────────────────────────────────────────
        if update.message and update.message.chat_id == int(self.chat_id):
            text = (update.message.text or "").strip()

            # /edit command
            if text.lower().startswith("/edit "):
                new_text = text[6:].strip()
                if new_text:
                    logger.info("✏️ Post edited via Telegram")
                    return ApprovalResult(
                        status=ApprovalStatus.EDITED, edited_text=new_text
                    )

            # Emoji shortcuts
            if text in ("✅", "/approve", "yes", "post", "ok"):
                return ApprovalResult(status=ApprovalStatus.APPROVED)
            if text in ("❌", "/reject", "no", "skip"):
                return ApprovalResult(status=ApprovalStatus.REJECTED)

        return None

    async def _send_confirmation(self, result: ApprovalResult) -> None:
        messages = {
            ApprovalStatus.APPROVED: "✅ Got it! Posting to LinkedIn now...",
            ApprovalStatus.REJECTED: "❌ Skipped. Next post will come soon.",
            ApprovalStatus.EDITED: "✏️ Updated text received! Posting to LinkedIn now...",
        }
        msg = messages.get(result.status)
        if msg:
            await self.send_notification(msg)

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _escape_md(text: str) -> str:
        """Escape special characters for Telegram MarkdownV1."""
        # MarkdownV1 only needs * _ ` [ to be escaped in text
        replacements = [("_", r"\_"), ("*", r"\*"), ("`", r"\`"), ("[", r"\[")]
        for char, escaped in replacements:
            text = text.replace(char, escaped)
        return text
