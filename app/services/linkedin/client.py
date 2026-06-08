"""Low-level LinkedIn UGC API client + payload/URN helpers.

Pure, mockable building blocks. The publisher composes these into the
text/image/poll/document flows.
"""

from __future__ import annotations

import logging
import urllib.parse

import aiohttp

from app.config import Settings
from app.models import PublishResult

logger = logging.getLogger(__name__)


class LinkedInTokenExpiredError(Exception):
    """Raised on HTTP 401 from LinkedIn (token expired or invalid)."""


# ── Pure helpers (unit-tested) ───────────────────────────────────────────────

def build_comment_url(post_urn: str) -> str:
    """Build the socialActions comments endpoint for a post URN.

    The URN's reserved characters (the colons) must be percent-encoded exactly
    once for the path variable.
    """
    encoded = urllib.parse.quote(post_urn, safe="")
    return f"https://api.linkedin.com/v2/socialActions/{encoded}/comments"


def text_payload(author_urn: str, text: str) -> dict:
    return {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }


def image_payload(author_urn: str, text: str, asset_urn: str) -> dict:
    return {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "IMAGE",
                "media": [{
                    "status": "READY",
                    "description": {"text": text[:200]},
                    "media": asset_urn,
                    "title": {"text": "Post image"},
                }],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }


def poll_payload(author_urn: str, full_text: str, question: str, options: list[str]) -> dict:
    return {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": full_text},
                "shareMediaCategory": "POLL",
                "media": [{
                    "status": "READY",
                    "poll": {
                        "question": question,
                        "options": [{"text": o[:30]} for o in options[:4]],
                        "settings": {"duration": "THREE_DAYS"},
                    },
                }],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }


def document_payload(author_urn: str, text: str, asset_urn: str, title: str) -> dict:
    return {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "DOCUMENT",
                "media": [{
                    "status": "READY",
                    "media": asset_urn,
                    "title": {"text": title[:200]},
                }],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }


def register_upload_payload(owner_urn: str, recipe: str) -> dict:
    return {
        "registerUploadRequest": {
            "recipes": [recipe],
            "owner": owner_urn,
            "serviceRelationships": [
                {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
            ],
        }
    }


# ── HTTP client ──────────────────────────────────────────────────────────────

class LinkedInClient:
    """Thin async wrapper over the LinkedIn UGC + assets + socialActions APIs."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._headers = {
            "Authorization": f"Bearer {settings.linkedin_access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    @property
    def headers(self) -> dict:
        return dict(self._headers)

    async def create_post(self, session: aiohttp.ClientSession, payload: dict) -> PublishResult:
        async with session.post(
            self._settings.linkedin_ugc_posts_url, json=payload, headers=self._headers
        ) as resp:
            return await self.parse_post_response(resp)

    async def register_upload(
        self, session: aiohttp.ClientSession, recipe: str
    ) -> tuple[str | None, str | None]:
        """Register an upload; returns (asset_urn, upload_url)."""
        payload = register_upload_payload(self._settings.linkedin_person_urn, recipe)
        async with session.post(
            self._settings.linkedin_assets_url, json=payload, headers=self._headers
        ) as resp:
            if resp.status != 200:
                logger.error("Register upload failed (%s): %s", resp.status, (await resp.text())[:200])
                return None, None
            value = (await resp.json()).get("value", {})
        upload_url = (
            value.get("uploadMechanism", {})
            .get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
            .get("uploadUrl")
        )
        asset_urn = value.get("asset")
        logger.info("Registered LinkedIn asset: %s", asset_urn)
        return asset_urn, upload_url

    async def upload_binary(
        self, session: aiohttp.ClientSession, upload_url: str, data: bytes
    ) -> bool:
        upload_headers = {
            "Authorization": f"Bearer {self._settings.linkedin_access_token}",
            "Content-Type": "application/octet-stream",
        }
        async with session.put(upload_url, data=data, headers=upload_headers) as resp:
            if resp.status in (200, 201):
                return True
            logger.error("Binary upload failed (%s): %s", resp.status, (await resp.text())[:200])
            return False

    async def post_comment(
        self, session: aiohttp.ClientSession, post_urn: str, comment_text: str
    ) -> bool:
        url = build_comment_url(post_urn)
        payload = {
            "actor": self._settings.linkedin_person_urn,
            "message": {"text": comment_text},
        }
        # IMPORTANT: the socialActions/comments endpoint must NOT receive the
        # "X-Restli-Protocol-Version: 2.0.0" header — with it, the encoded URN
        # in the path triggers a 400 "Syntax exception in path variables".
        # Verified live: dropping the header makes the comment succeed (201).
        comment_headers = {
            "Authorization": f"Bearer {self._settings.linkedin_access_token}",
            "Content-Type": "application/json",
        }
        async with session.post(url, json=payload, headers=comment_headers) as resp:
            if resp.status in (200, 201):
                logger.info("First comment posted successfully")
                return True
            logger.warning("Comment post failed (%s): %s", resp.status, (await resp.text())[:200])
            return False

    async def parse_post_response(self, resp: aiohttp.ClientResponse) -> PublishResult:
        body = await resp.text()
        if resp.status == 401:
            raise LinkedInTokenExpiredError("LinkedIn token expired or invalid")
        if resp.status == 429:
            logger.warning("LinkedIn rate limit hit")
            return PublishResult(success=False, error="Rate limit exceeded — will retry later")
        if resp.status not in (200, 201):
            logger.error("LinkedIn post failed (%s): %s", resp.status, body)
            return PublishResult(success=False, error=f"HTTP {resp.status}: {body[:200]}")

        post_id = resp.headers.get("X-RestLi-Id") or resp.headers.get("x-restli-id")
        post_url = f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else None
        logger.info("LinkedIn post published: %s", post_url or post_id)
        return PublishResult(success=True, post_id=post_id, post_url=post_url)
