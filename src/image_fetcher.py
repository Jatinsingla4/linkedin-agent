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

# Curated fallback images per topic category (Unsplash direct image URLs)
FALLBACK_IMAGES = {
    "marketing": [
        "https://images.unsplash.com/photo-1533750349088-cd871a92f312?w=1200",
        "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1200",
    ],
    "branding": [
        "https://images.unsplash.com/photo-1611532736597-de2d4265fba3?w=1200",
        "https://images.unsplash.com/photo-1558655146-9f40138edfeb?w=1200",
    ],
    "technology": [
        "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1200",
        "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1200",
    ],
    "business": [
        "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=1200",
        "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=1200",
    ],
    "default": [
        "https://images.unsplash.com/photo-1499750310107-5fef28a66643?w=1200",
        "https://images.unsplash.com/photo-1521737852567-6949f3f9f2b5?w=1200",
    ],
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
