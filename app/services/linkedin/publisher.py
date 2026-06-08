"""High-level LinkedIn publishing flows.

Composes :class:`LinkedInClient` building blocks into text/image/poll/document
posts, with graceful fallbacks and a dry-run guard.
"""

from __future__ import annotations

import logging
import os

from app.config import Settings
from app.core.http import create_session
from app.models import PublishResult
from app.services.linkedin import client as api

logger = logging.getLogger(__name__)

IMAGE_RECIPE = "urn:li:digitalmediaRecipe:feedshare-image"
DOCUMENT_RECIPE = "urn:li:digitalmediaRecipe:feedshare-document"


class LinkedInPublisher:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = api.LinkedInClient(settings)

    @property
    def _author(self) -> str:
        return self._settings.linkedin_person_urn

    def _dry_run_result(self, kind: str) -> PublishResult:
        logger.info("DRY_RUN: skipping LinkedIn %s publish", kind)
        return PublishResult(success=True, post_id="dry-run", post_url="(dry-run, not published)")

    # ── Text / image ─────────────────────────────────────────
    async def publish(self, text: str, image_path: str | None = None) -> PublishResult:
        if self._settings.dry_run:
            return self._dry_run_result("post")
        try:
            if image_path and os.path.exists(image_path):
                return await self._publish_with_image(text, image_path)
            return await self._publish_text(text)
        except api.LinkedInTokenExpiredError:
            return PublishResult(
                success=False,
                error=(
                    "❌ LinkedIn access token has expired.\n"
                    "Refresh it at https://www.linkedin.com/developers/apps "
                    "then update LINKEDIN_ACCESS_TOKEN."
                ),
            )
        except Exception as e:
            logger.error("LinkedIn publish failed: %s", e)
            return PublishResult(success=False, error=str(e))

    async def _publish_text(self, text: str) -> PublishResult:
        async with create_session() as session:
            return await self._client.create_post(session, api.text_payload(self._author, text))

    async def _publish_with_image(self, text: str, image_path: str) -> PublishResult:
        async with create_session() as session:
            asset_urn, upload_url = await self._client.register_upload(session, IMAGE_RECIPE)
            if not asset_urn or not upload_url:
                logger.warning("Image registration failed — falling back to text-only")
                return await self._client.create_post(session, api.text_payload(self._author, text))

            with open(image_path, "rb") as f:
                if not await self._client.upload_binary(session, upload_url, f.read()):
                    logger.warning("Image upload failed — falling back to text-only")
                    return await self._client.create_post(
                        session, api.text_payload(self._author, text)
                    )

            return await self._client.create_post(
                session, api.image_payload(self._author, text, asset_urn)
            )

    # ── Poll ─────────────────────────────────────────────────
    async def publish_poll(
        self, intro_text: str, question: str, options: list[str], hashtags: list[str]
    ) -> PublishResult:
        if self._settings.dry_run:
            return self._dry_run_result("poll")
        hashtag_line = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
        full_text = f"{intro_text}\n\n{hashtag_line}".strip()
        try:
            async with create_session() as session:
                result = await self._client.create_post(
                    session, api.poll_payload(self._author, full_text, question, options)
                )
                if result.success:
                    return result
                logger.warning("Poll API failed — falling back to text post")
                fallback = full_text + f"\n\n🗳️ {question}\n" + "\n".join(f"• {o}" for o in options)
                return await self._client.create_post(
                    session, api.text_payload(self._author, fallback)
                )
        except Exception as e:
            logger.error("Poll publish error: %s — falling back to text", e)
            return await self._publish_text(full_text)

    # ── Document (carousel) ──────────────────────────────────
    async def publish_document(self, text: str, pdf_path: str, title: str) -> PublishResult:
        if self._settings.dry_run:
            return self._dry_run_result("document")
        async with create_session() as session:
            asset_urn, upload_url = await self._client.register_upload(session, DOCUMENT_RECIPE)
            if not asset_urn or not upload_url:
                return await self._client.create_post(session, api.text_payload(self._author, text))

            with open(pdf_path, "rb") as f:
                if not await self._client.upload_binary(session, upload_url, f.read()):
                    return await self._client.create_post(
                        session, api.text_payload(self._author, text)
                    )

            return await self._client.create_post(
                session, api.document_payload(self._author, text, asset_urn, title)
            )

    # ── First comment ────────────────────────────────────────
    async def post_comment(self, post_urn: str, comment_text: str) -> bool:
        if self._settings.dry_run:
            logger.info("DRY_RUN: skipping comment")
            return True
        try:
            async with create_session() as session:
                return await self._client.post_comment(session, post_urn, comment_text)
        except Exception as e:
            logger.error("Comment post error: %s", e)
            return False
