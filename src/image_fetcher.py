"""
image_fetcher.py — Fetches relevant images for posts.

Strategy:
  1. Try Unsplash API (free, high quality stock photos)
  2. Fallback: Pick from curated topic-based image URLs
  3. Returns local file path of downloaded image

Image is downloaded temporarily for upload to LinkedIn.
"""

import logging
import os
import random
import re
import tempfile
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import config

logger = logging.getLogger(__name__)

# Curated fallback images — picsum.photos gives reliable random professional images
FALLBACK_IMAGES = {
    "marketing":   ["https://picsum.photos/seed/mktg1/1200/628", "https://picsum.photos/seed/mktg2/1200/628"],
    "branding":    ["https://picsum.photos/seed/brand1/1200/628", "https://picsum.photos/seed/brand2/1200/628"],
    "technology":  ["https://picsum.photos/seed/tech1/1200/628", "https://picsum.photos/seed/tech2/1200/628"],
    "business":    ["https://picsum.photos/seed/biz1/1200/628", "https://picsum.photos/seed/biz2/1200/628"],
    "ai":          ["https://picsum.photos/seed/ai1/1200/628", "https://picsum.photos/seed/ai2/1200/628"],
    "default":     ["https://picsum.photos/seed/post1/1200/628", "https://picsum.photos/seed/post2/1200/628"],
}


@dataclass
class FetchedImage:
    file_path: str          # Local temp file path
    unsplash_url: str       # Original image URL
    photographer: str       # Attribution (good practice)
    alt_text: str           # For accessibility


class ImageFetcher:

    # ── Public interface ──────────────────────────────────────────────────────

    async def fetch_image(self, query: str) -> Optional[FetchedImage]:
        """
        Fetch the best image for the given query.
        Returns None if all methods fail (post will be text-only).
        """
        # Try Unsplash first
        image = await self._fetch_from_unsplash(query)
        if image:
            return image

        # Fallback to curated images
        logger.warning(f"Unsplash failed for '{query}' — using fallback image")
        return await self._fetch_fallback(query)

    # ── Unsplash ──────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _fetch_from_unsplash(self, query: str) -> Optional[FetchedImage]:
        search_url = "https://api.unsplash.com/search/photos"
        params = {
            "query": query,
            "per_page": 5,
            "orientation": "landscape",
            "content_filter": "high",
        }
        headers = {
            "Authorization": f"Client-ID {config.unsplash_access_key}"
        }

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(search_url, params=params, headers=headers) as resp:
                if resp.status == 403:
                    logger.error("Unsplash: Invalid API key or rate limit exceeded")
                    return None
                if resp.status != 200:
                    logger.warning(f"Unsplash returned {resp.status}")
                    return None
                data = await resp.json()

            results = data.get("results", [])
            if not results:
                logger.warning(f"Unsplash: no results for '{query}'")
                return None

            # Pick best result (highest likes = community-validated quality)
            best = max(results, key=lambda x: x.get("likes", 0))
            image_url = best["urls"]["regular"]  # 1080px wide
            photographer = best["user"]["name"]
            alt_text = best.get("alt_description") or query

            # Download inside session so it's still open
            file_path = await self._download_image(session, image_url)
            if not file_path:
                return None

            logger.info(f"ImageFetcher: fetched from Unsplash — '{query}' by {photographer}")
            return FetchedImage(
                file_path=file_path,
                unsplash_url=image_url,
                photographer=photographer,
                alt_text=alt_text,
            )

    # ── Fallback ──────────────────────────────────────────────────────────────

    async def _fetch_fallback(self, query: str) -> Optional[FetchedImage]:
        # Match query to a category
        category = "default"
        query_lower = query.lower()
        for cat in FALLBACK_IMAGES:
            if cat in query_lower:
                category = cat
                break

        image_url = random.choice(FALLBACK_IMAGES[category])

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            file_path = await self._download_image(session, image_url)

        if not file_path:
            return None

        return FetchedImage(
            file_path=file_path,
            unsplash_url=image_url,
            photographer="Unsplash",
            alt_text=query,
        )

    # ── Download utility ──────────────────────────────────────────────────────

    async def _download_image(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[str]:
        """Download image to a temp file, return its path."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None

                content_type = resp.headers.get("Content-Type", "image/jpeg")
                ext = self._ext_from_content_type(content_type)

                # Use NamedTemporaryFile — caller is responsible for cleanup
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=ext, prefix="linkedin_img_"
                )
                tmp.write(await resp.read())
                tmp.close()

                file_size_kb = Path(tmp.name).stat().st_size / 1024
                logger.info(f"ImageFetcher: downloaded {file_size_kb:.0f}KB → {tmp.name}")
                return tmp.name

        except Exception as e:
            logger.error(f"ImageFetcher: download failed: {e}")
            return None

    @staticmethod
    def _ext_from_content_type(content_type: str) -> str:
        mapping = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        return mapping.get(content_type.split(";")[0].strip(), ".jpg")

    @staticmethod
    def cleanup(file_path: str) -> None:
        """Delete temp image file after it's been used."""
        try:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"ImageFetcher: cleaned up {file_path}")
        except Exception as e:
            logger.warning(f"ImageFetcher: cleanup failed: {e}")
