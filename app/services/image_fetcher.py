"""Fetches a relevant image for a post.

  1. Unsplash search (free, high quality)
  2. Fallback: curated picsum.photos images by category
The image is downloaded to a temp file for upload; callers must clean it up
via :meth:`ImageFetcher.cleanup`.
"""

from __future__ import annotations

import logging
import os
import random
import tempfile
from pathlib import Path

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings
from app.core.http import create_session
from app.models import FetchedImage

logger = logging.getLogger(__name__)

FALLBACK_IMAGES = {
    "marketing": ["https://picsum.photos/seed/mktg1/1200/628", "https://picsum.photos/seed/mktg2/1200/628"],
    "branding": ["https://picsum.photos/seed/brand1/1200/628", "https://picsum.photos/seed/brand2/1200/628"],
    "technology": ["https://picsum.photos/seed/tech1/1200/628", "https://picsum.photos/seed/tech2/1200/628"],
    "business": ["https://picsum.photos/seed/biz1/1200/628", "https://picsum.photos/seed/biz2/1200/628"],
    "ai": ["https://picsum.photos/seed/ai1/1200/628", "https://picsum.photos/seed/ai2/1200/628"],
    "default": ["https://picsum.photos/seed/post1/1200/628", "https://picsum.photos/seed/post2/1200/628"],
}

_EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class ImageFetcher:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def fetch_image(self, query: str) -> FetchedImage | None:
        image = await self._fetch_from_unsplash(query)
        if image:
            return image
        logger.warning("Unsplash failed for '%s' — using fallback image", query)
        return await self._fetch_fallback(query)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _fetch_from_unsplash(self, query: str) -> FetchedImage | None:
        params = {"query": query, "per_page": 5, "orientation": "landscape", "content_filter": "high"}
        headers = {"Authorization": f"Client-ID {self._settings.unsplash_access_key}"}

        async with create_session() as session:
            async with session.get(
                "https://api.unsplash.com/search/photos", params=params, headers=headers
            ) as resp:
                if resp.status == 403:
                    logger.error("Unsplash: invalid API key or rate limit exceeded")
                    return None
                if resp.status != 200:
                    logger.warning("Unsplash returned %s", resp.status)
                    return None
                data = await resp.json()

            results = data.get("results", [])
            if not results:
                logger.warning("Unsplash: no results for '%s'", query)
                return None

            best = max(results, key=lambda x: x.get("likes", 0))
            image_url = best["urls"]["regular"]
            file_path = await self._download(session, image_url)
            if not file_path:
                return None

            logger.info("ImageFetcher: Unsplash hit for '%s' by %s", query, best["user"]["name"])
            return FetchedImage(
                file_path=file_path,
                source_url=image_url,
                photographer=best["user"]["name"],
                alt_text=best.get("alt_description") or query,
            )

    async def _fetch_fallback(self, query: str) -> FetchedImage | None:
        category = next((c for c in FALLBACK_IMAGES if c in query.lower()), "default")
        image_url = random.choice(FALLBACK_IMAGES[category])
        async with create_session() as session:
            file_path = await self._download(session, image_url)
        if not file_path:
            return None
        return FetchedImage(
            file_path=file_path, source_url=image_url, photographer="picsum", alt_text=query
        )

    async def _download(self, session: aiohttp.ClientSession, url: str) -> str | None:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                ext = _EXT_BY_TYPE.get(
                    resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip(), ".jpg"
                )
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix="linkedin_img_")
                tmp.write(await resp.read())
                tmp.close()
                size_kb = Path(tmp.name).stat().st_size / 1024
                logger.info("ImageFetcher: downloaded %.0fKB -> %s", size_kb, tmp.name)
                return tmp.name
        except Exception as e:
            logger.error("ImageFetcher: download failed: %s", e)
            return None

    @staticmethod
    def cleanup(file_path: str | None) -> None:
        try:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug("ImageFetcher: cleaned up %s", file_path)
        except Exception as e:
            logger.warning("ImageFetcher: cleanup failed: %s", e)
