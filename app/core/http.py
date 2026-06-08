"""Shared aiohttp session factory.

Replaces the scattered ``aiohttp.TCPConnector(ssl=False)`` calls that disabled
certificate verification everywhere. Here we build a proper SSL context backed
by certifi, with sane timeouts and a default User-Agent.

Usage::

    async with create_session() as session:
        async with session.get(url) as resp:
            ...
"""

from __future__ import annotations

import ssl

import aiohttp
import certifi

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
DEFAULT_HEADERS = {"User-Agent": "LinkedInAgent/2.0 (personal automation)"}


def ssl_context() -> ssl.SSLContext:
    """A verified SSL context using certifi's CA bundle."""
    return ssl.create_default_context(cafile=certifi.where())


def create_session(
    *,
    timeout: aiohttp.ClientTimeout | None = None,
    headers: dict[str, str] | None = None,
) -> aiohttp.ClientSession:
    """Create a client session with verified TLS and shared defaults."""
    connector = aiohttp.TCPConnector(ssl=ssl_context())
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    return aiohttp.ClientSession(
        connector=connector,
        timeout=timeout or DEFAULT_TIMEOUT,
        headers=merged_headers,
    )
