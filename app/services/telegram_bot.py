"""Telegram approval bot — human-in-the-loop preview & control.

Transport only: sends previews, polls ``getUpdates`` for the user's decision,
and returns typed results. Content rewriting is delegated to an injected
:class:`ContentWriter` (no runtime monkeypatching).

Commands understood during version selection:
  • Inline buttons: ✅ Version N / ❌ Skip
  • ``/newtopic <idea>``  → regenerate on a new topic now
  • ``/url <link>``       → generate from an article/link now
  • ``/edit <text>``      → publish the user's own text
  • a photo              → use the user's image
  • free text replying to a version → AI rewrite of that version
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from datetime import UTC, datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app import strings
from app.config import Settings
from app.models import NEWTOPIC_PREFIX, URL_PREFIX, GeneratedPost, VersionSelection

logger = logging.getLogger(__name__)

APPROVE_CALLBACK = "approve"
REJECT_CALLBACK = "reject"
POLL_INTERVAL = 5
SUGGESTION_WINDOW_SECONDS = 3600


class ApprovalBot:
    def __init__(self, settings: Settings, content_writer=None):
        self._settings = settings
        self.bot = Bot(token=settings.telegram_bot_token)
        self.chat_id = settings.telegram_chat_id
        self.content_writer = content_writer  # injected, used for conversational rewrites

    # ── Notifications ────────────────────────────────────────
    async def send_notification(self, message: str) -> None:
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, text=message, parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError as e:
            logger.error("Failed to send Telegram notification: %s", e)

    # ── Pre-run suggestions (/topic, /url) ───────────────────
    async def get_topic_suggestion(self) -> str | None:
        return await self._recent_command("/topic ")

    async def get_url_suggestion(self) -> str | None:
        value = await self._recent_command("/url ")
        return value if (value and value.startswith("http")) else None

    async def _recent_command(self, prefix: str) -> str | None:
        try:
            updates = await self.bot.get_updates(timeout=2, allowed_updates=["message"], limit=20)
            cutoff = datetime.now(UTC).timestamp() - SUGGESTION_WINDOW_SECONDS
            for update in reversed(updates):
                msg = update.message
                if not msg or msg.chat_id != int(self.chat_id):
                    continue
                if msg.date.timestamp() < cutoff:
                    continue
                text = (msg.text or "").strip()
                if text.lower().startswith(prefix.strip()):
                    value = text[len(prefix):].strip()
                    if value:
                        logger.info("Found Telegram command %s: %s", prefix.strip(), value)
                        return value
        except TelegramError as e:
            logger.debug("Could not check command %s: %s", prefix, e)
        return None

    # ── Update polling helpers ───────────────────────────────
    async def _start_offset(self) -> int:
        try:
            updates = await self.bot.get_updates(
                timeout=2, limit=100, allowed_updates=["message", "callback_query"]
            )
            if updates:
                return updates[-1].update_id
        except TelegramError:
            pass
        return -1

    async def _poll_updates(self, offset: int) -> list[Update]:
        try:
            return await self.bot.get_updates(
                offset=offset + 1 if offset > 0 else None,
                timeout=4,
                allowed_updates=["message", "callback_query"],
            )
        except TelegramError as e:
            logger.debug("getUpdates error (non-fatal): %s", e)
            return []

    def _is_our_chat(self, update: Update) -> bool:
        return bool(update.message and update.message.chat_id == int(self.chat_id))

    # ── Version selection ────────────────────────────────────
    async def request_version_selection(
        self, posts: list[GeneratedPost], topic: str, image_path: str | None = None
    ) -> VersionSelection:
        version_msg_ids = await self._send_versions(posts)
        keyboard = self._selection_keyboard(len(posts))
        msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text=self._selection_prompt(topic),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return await self._await_version_response(msg.message_id, posts, version_msg_ids, keyboard)

    async def _send_versions(self, posts: list[GeneratedPost]) -> dict[int, int]:
        """Send each version (chunked to Telegram's 4096 limit). Returns msg_id→index."""
        version_msg_ids: dict[int, int] = {}
        for i, post in enumerate(posts):
            header = f"📝 *Version {i + 1}:*\n\n"
            text = header + self._escape(post.full_text)
            last_msg = None
            for chunk_start in range(0, len(text), 4000):
                last_msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text[chunk_start:chunk_start + 4000],
                    parse_mode=ParseMode.MARKDOWN,
                )
                await asyncio.sleep(0.4)
            if last_msg:
                version_msg_ids[last_msg.message_id] = i
            await asyncio.sleep(0.6)
        return version_msg_ids

    def _selection_keyboard(self, n: int) -> InlineKeyboardMarkup:
        buttons = [
            InlineKeyboardButton(f"✅ Version {i + 1}", callback_data=f"v{i}") for i in range(n)
        ]
        return InlineKeyboardMarkup([buttons, [InlineKeyboardButton("❌ Skip all", callback_data=REJECT_CALLBACK)]])

    def _selection_prompt(self, topic: str) -> str:
        return (
            f"👆 *Pick a version to post*\n"
            f"📌 Topic: _{self._escape(topic[:80])}_\n\n"
            f"{strings.DIVIDER}\n"
            f"*Commands:*\n"
            f"🔄 `/newtopic <apna topic>` — abhi naya post banao\n"
            f"🔗 `/url <article ya insta link>` — us link pe post banao\n"
            f"✏️ `/edit <poora post text>` — apna text directly post karo\n"
            f"📸 *Photo bhejo* — apni image use hogi\n"
            f"💡 `/topic <idea>` — kal ke liye queue mein daalo\n"
            f"❌ Skip karna ho toh neeche button dabao"
        )

    async def _await_version_response(
        self,
        message_id: int,
        posts: list[GeneratedPost],
        version_msg_ids: dict[int, int],
        keyboard: InlineKeyboardMarkup,
    ) -> VersionSelection:
        timeout = self._settings.approval_timeout_hours * 3600
        elapsed = 0
        offset = await self._start_offset()
        user_image_path: str | None = None

        while elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            for update in await self._poll_updates(offset):
                offset = max(offset, update.update_id)

                # Inline buttons
                cq = update.callback_query
                if cq and cq.message and cq.message.message_id == message_id:
                    if cq.data == REJECT_CALLBACK:
                        await self.send_notification("❌ Skipped. Next post coming soon!")
                        return VersionSelection()
                    for i in range(len(posts)):
                        if cq.data == f"v{i}":
                            note = " (apni photo ke saath!)" if user_image_path else ""
                            await self.send_notification(f"✅ Version {i + 1} selected{note} Posting...")
                            return VersionSelection(selected_post=posts[i], user_image_path=user_image_path)

                if not self._is_our_chat(update):
                    continue

                # Photo upload
                if update.message.photo:
                    path = await self._download_photo(update)
                    if path:
                        user_image_path = path
                        await self.send_notification(strings.PHOTO_RECEIVED)
                    continue

                text = (update.message.text or "").strip()
                command_result = self._match_command(text, posts, user_image_path)
                if command_result is not None:
                    if command_result.newtopic or command_result.url:
                        await self.send_notification("🔄 Got it! Ek minute...")
                    return command_result

                if text in ("❌", "/reject", "no", "skip"):
                    await self.send_notification("❌ Skipped.")
                    return VersionSelection()

                # Conversational rewrite (free text replying to a version)
                if text and not text.startswith("/"):
                    message_id = await self._maybe_rewrite(
                        update, text, posts, version_msg_ids, keyboard, message_id
                    )

        await self.send_notification(
            f"⏰ Timed out after {self._settings.approval_timeout_hours}h — skipped."
        )
        return VersionSelection()

    def _match_command(
        self, text: str, posts: list[GeneratedPost], user_image_path: str | None
    ) -> VersionSelection | None:
        low = text.lower()
        if low.startswith("/newtopic "):
            value = text[len("/newtopic "):].strip()
            if value:
                return VersionSelection(posts[0], NEWTOPIC_PREFIX + value, user_image_path)
        if low.startswith("/url "):
            value = text[len("/url "):].strip()
            if value.startswith("http"):
                return VersionSelection(posts[0], URL_PREFIX + value, user_image_path)
        if low.startswith("/edit "):
            value = text[len("/edit "):].strip()
            if value:
                return VersionSelection(posts[0], value, user_image_path)
        return None

    async def _maybe_rewrite(
        self,
        update: Update,
        text: str,
        posts: list[GeneratedPost],
        version_msg_ids: dict[int, int],
        keyboard: InlineKeyboardMarkup,
        message_id: int,
    ) -> int:
        """Rewrite a version on a free-text instruction. Returns the (maybe new) selection message id."""
        target_idx = None
        instruction = ""

        reply = update.message.reply_to_message
        if reply and reply.message_id in version_msg_ids:
            target_idx = version_msg_ids[reply.message_id]
            instruction = text
        else:
            m = re.match(r"^(v|version)\s*(\d+)[:\-\s]+(.*)$", text, re.IGNORECASE)
            if m and 1 <= int(m.group(2)) <= len(posts):
                target_idx = int(m.group(2)) - 1
                instruction = m.group(3).strip()

        if target_idx is None or not instruction or not self.content_writer:
            return message_id

        await self.send_notification(
            f"🔄 *Rewriting Version {target_idx + 1}...*\n"
            f"Instruction: _{self._escape(instruction)}_\n_Ek minute..._"
        )
        try:
            rewritten = await self.content_writer.rewrite_post(
                posts[target_idx].full_text, instruction
            )
            posts[target_idx].full_text = rewritten
            new_msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"📝 *Version {target_idx + 1} (Edited):*\n\n" + self._escape(rewritten),
                parse_mode=ParseMode.MARKDOWN,
            )
            version_msg_ids[new_msg.message_id] = target_idx
            select_msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text="👆 *Pick a version or reply to edit again:*",
                reply_markup=keyboard,
            )
            return select_msg.message_id
        except Exception as e:
            logger.error("Failed to rewrite post: %s", e)
            await self.send_notification(f"❌ Rewrite failed: `{e}`")
            return message_id

    async def _download_photo(self, update: Update) -> str | None:
        try:
            photo = update.message.photo[-1]
            tg_file = await self.bot.get_file(photo.file_id)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg", prefix="user_img_")
            tmp.close()
            await tg_file.download_to_drive(tmp.name)
            logger.info("User image received: %s", tmp.name)
            return tmp.name
        except Exception as e:
            logger.warning("Failed to download user photo: %s", e)
            return None

    # ── Poll approval ────────────────────────────────────────
    async def request_poll_approval(
        self, intro_text: str, question: str, options: list[str], topic: str
    ) -> bool:
        options_text = "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(options))
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Post Poll", callback_data=APPROVE_CALLBACK),
            InlineKeyboardButton("❌ Skip", callback_data=REJECT_CALLBACK),
        ]])
        msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"🗳️ *Poll Preview*\n{strings.DIVIDER}\n"
                f"📌 Topic: _{self._escape(topic[:80])}_\n\n"
                f"*Intro:* {self._escape(intro_text[:300])}\n\n"
                f"*Question:* {self._escape(question)}\n\n"
                f"{self._escape(options_text)}\n\n"
                f"Auto-skips in {self._settings.approval_timeout_hours}h."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return await self._await_simple_approval(msg.message_id)

    async def _await_simple_approval(self, message_id: int) -> bool:
        timeout = self._settings.approval_timeout_hours * 3600
        elapsed = 0
        offset = await self._start_offset()
        while elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            for update in await self._poll_updates(offset):
                offset = max(offset, update.update_id)
                cq = update.callback_query
                if cq and cq.message and cq.message.message_id == message_id:
                    return cq.data == APPROVE_CALLBACK
                if self._is_our_chat(update):
                    text = (update.message.text or "").strip().lower()
                    if text in ("✅", "/approve", "yes", "post", "ok"):
                        return True
                    if text in ("❌", "/reject", "no", "skip"):
                        return False
        return False

    # ── Calendar approval ────────────────────────────────────
    async def request_calendar_approval(self, topics: list[str]) -> list[str]:
        topics_text = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(topics))
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve All", callback_data=APPROVE_CALLBACK),
            InlineKeyboardButton("❌ Skip Week", callback_data=REJECT_CALLBACK),
        ]])
        msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"📅 *This Week's Content Plan*\n{strings.DIVIDER}\n"
                f"{self._escape(topics_text)}\n\n"
                f"Tap ✅ to approve or reply `/skip 2,4` to remove specific topics.\n"
                f"Auto-approves in 30 min."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )

        approved = list(topics)
        offset = -1
        elapsed = 0
        while elapsed < 1800:  # 30 min
            await asyncio.sleep(10)
            elapsed += 10
            for update in await self._poll_updates(offset):
                offset = max(offset, update.update_id)
                cq = update.callback_query
                if cq and cq.message and cq.message.message_id == msg.message_id:
                    if cq.data == APPROVE_CALLBACK:
                        await self.send_notification(f"✅ Content plan approved! {len(approved)} topics queued.")
                        return approved
                    if cq.data == REJECT_CALLBACK:
                        await self.send_notification("❌ Content plan skipped.")
                        return []
                if self._is_our_chat(update):
                    text = (update.message.text or "").strip()
                    if text.lower().startswith("/skip "):
                        try:
                            skip = {int(x.strip()) - 1 for x in text[6:].split(",")}
                            approved = [t for i, t in enumerate(topics) if i not in skip]
                            await self.send_notification(
                                f"✅ Plan updated! {len(approved)} topics queued:\n"
                                + "\n".join(f"• {t[:60]}" for t in approved)
                            )
                            return approved
                        except ValueError:
                            pass

        await self.send_notification(f"⏰ Auto-approved {len(approved)} topics for this week!")
        return approved

    # ── Utilities ────────────────────────────────────────────
    @staticmethod
    def _escape(text: str) -> str:
        for ch, esc in (("_", r"\_"), ("*", r"\*"), ("`", r"\`"), ("[", r"\[")):
            text = text.replace(ch, esc)
        return text
