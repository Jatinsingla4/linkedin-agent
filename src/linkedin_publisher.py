"""
linkedin_publisher.py — Posts content to LinkedIn via the official UGC Posts API.

Handles:
  - Text-only posts
  - Image posts (registers asset → uploads image → creates post)
  - Token expiry detection with clear error messages
  - Rate limit handling
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    success: bool
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    error: Optional[str] = None


class LinkedInTokenExpiredError(Exception):
    pass


class LinkedInPublisher:

    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {config.linkedin_access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ── Public interface ──────────────────────────────────────────────────────

    async def publish(
        self,
        text: str,
        image_path: Optional[str] = None,
    ) -> PublishResult:
        """
        Publish a post. If image_path is provided, uploads image first.
        Returns PublishResult with success status and post URL.
        """
        try:
            if image_path and os.path.exists(image_path):
                return await self._publish_with_image(text, image_path)
            else:
                return await self._publish_text_only(text)
        except LinkedInTokenExpiredError:
            return PublishResult(
                success=False,
                error=(
                    "❌ LinkedIn access token has expired.\n"
                    "Please refresh it at: https://www.linkedin.com/developers/apps\n"
                    "Then update LINKEDIN_ACCESS_TOKEN in your .env / GitHub Secrets."
                )
            )
        except Exception as e:
            logger.error(f"LinkedIn publish failed: {e}")
            return PublishResult(success=False, error=str(e))

    # ── Text-only post ────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        retry=retry_if_exception_type(aiohttp.ClientError),
    )
    async def _publish_text_only(self, text: str) -> PublishResult:
        payload = self._build_text_payload(text)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                config.linkedin_ugc_posts_url,
                json=payload,
                headers=self._headers,
            ) as resp:
                return await self._handle_post_response(resp)

    # ── Image post ────────────────────────────────────────────────────────────

    async def _publish_with_image(self, text: str, image_path: str) -> PublishResult:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Step 1: Register the upload
            asset_urn = await self._register_image_upload(session)
            if not asset_urn:
                logger.warning("Image upload registration failed — falling back to text-only post")
                return await self._publish_text_only(text)

            # Step 2: Upload the image binary
            upload_ok = await self._upload_image_binary(session, asset_urn, image_path)
            if not upload_ok:
                logger.warning("Image binary upload failed — falling back to text-only post")
                return await self._publish_text_only(text)

            # Step 3: Create post referencing the asset
            payload = self._build_image_payload(text, asset_urn)
            async with session.post(
                config.linkedin_ugc_posts_url,
                json=payload,
                headers=self._headers,
            ) as resp:
                return await self._handle_post_response(resp)

    async def _register_image_upload(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Registers the upload and returns the asset URN + upload URL."""
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": config.linkedin_person_urn,
                "serviceRelationships": [{
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }]
            }
        }

        async with session.post(
            config.linkedin_assets_url,
            json=payload,
            headers=self._headers,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(f"Register upload failed ({resp.status}): {body}")
                return None

            data = await resp.json()
            value = data.get("value", {})
            self._upload_url = (
                value.get("uploadMechanism", {})
                     .get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
                     .get("uploadUrl")
            )
            asset_urn = value.get("asset")
            logger.info(f"Registered LinkedIn asset: {asset_urn}")
            return asset_urn

    async def _upload_image_binary(
        self, session: aiohttp.ClientSession, asset_urn: str, image_path: str
    ) -> bool:
        if not hasattr(self, "_upload_url") or not self._upload_url:
            logger.error("No upload URL available")
            return False

        with open(image_path, "rb") as f:
            image_data = f.read()

        upload_headers = {
            "Authorization": f"Bearer {config.linkedin_access_token}",
            "Content-Type": "application/octet-stream",
        }

        async with session.put(
            self._upload_url,
            data=image_data,
            headers=upload_headers,
        ) as resp:
            if resp.status in (200, 201):
                logger.info(f"Image uploaded successfully for asset {asset_urn}")
                return True
            else:
                body = await resp.text()
                logger.error(f"Image upload failed ({resp.status}): {body}")
                return False

    # ── Response handling ─────────────────────────────────────────────────────

    async def _handle_post_response(self, resp: aiohttp.ClientResponse) -> PublishResult:
        body = await resp.text()

        if resp.status == 401:
            raise LinkedInTokenExpiredError("LinkedIn token expired or invalid")

        if resp.status == 429:
            logger.warning("LinkedIn rate limit hit")
            return PublishResult(success=False, error="Rate limit exceeded — will retry later")

        if resp.status not in (200, 201):
            logger.error(f"LinkedIn post failed ({resp.status}): {body}")
            return PublishResult(success=False, error=f"HTTP {resp.status}: {body[:200]}")

        post_id = resp.headers.get("X-RestLi-Id") or resp.headers.get("x-restli-id")
        post_url = f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else None

        logger.info(f"✅ LinkedIn post published: {post_url or post_id}")
        return PublishResult(success=True, post_id=post_id, post_url=post_url)

    # ── Payload builders ──────────────────────────────────────────────────────

    async def post_comment(self, post_urn: str, comment_text: str) -> bool:
        """Post a first comment on a just-published post."""
        import urllib.parse
        encoded_urn = urllib.parse.quote(post_urn, safe="")
        url = f"https://api.linkedin.com/v2/socialActions/{encoded_urn}/comments"
        payload = {
            "actor": config.linkedin_person_urn,
            "message": {"text": comment_text},
        }
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url, json=payload, headers=self._headers) as resp:
                    if resp.status in (200, 201):
                        logger.info("First comment posted successfully")
                        return True
                    body = await resp.text()
                    logger.warning(f"Comment post failed ({resp.status}): {body[:200]}")
                    return False
        except Exception as e:
            logger.error(f"Comment post error: {e}")
            return False

    def _build_text_payload(self, text: str) -> dict:
        return {
            "author": config.linkedin_person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }

    def _build_image_payload(self, text: str, asset_urn: str) -> dict:
        return {
            "author": config.linkedin_person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE",
                    "media": [{
                        "status": "READY",
                        "description": {"text": text[:200]},
                        "media": asset_urn,
                        "title": {"text": "Post image"}
                    }]
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
