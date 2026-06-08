"""ContentWriter parsing + Gemini JSON helpers + format rotation."""

from __future__ import annotations

import random

import pytest

from app.models import Topic
from app.services.content import prompts
from app.services.content.writer import ContentWriter
from app.services.gemini_client import strip_code_fences
from tests.conftest import make_settings


def writer() -> ContentWriter:
    return ContentWriter(make_settings(), gemini=None)  # _parse_post doesn't touch gemini


def _payload(**overrides) -> dict:
    base = {
        "hook": "A bold hook",
        "body": "Body line one.\nBody line two.",
        "cta": "What do you think?",
        "hashtags": ["Marketing", "#AI", "branding"],
        "image_query": "brand strategy",
        "post_type": "image",
    }
    base.update(overrides)
    return base


def test_parse_post_happy_path():
    post = writer()._parse_post(_payload(), Topic(title="Topic X", source="rss"))
    assert post.hook == "A bold hook"
    assert post.hashtags == ["#marketing", "#ai", "#branding"]  # normalised
    assert post.topic == "Topic X"
    assert post.word_count > 0
    assert post.hook in post.full_text and post.cta in post.full_text


def test_parse_post_missing_field_raises():
    bad = _payload()
    del bad["cta"]
    with pytest.raises(ValueError, match="missing fields"):
        writer()._parse_post(bad, Topic(title="T", source="rss"))


def test_strip_code_fences():
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'


def test_post_formats_are_eight_and_unique():
    names = [f["name"] for f in prompts.POST_FORMATS]
    assert len(names) == 8
    assert len(set(names)) == 8


def test_format_rotation_picks_distinct():
    chosen = random.sample(prompts.POST_FORMATS, k=2)
    assert chosen[0]["name"] != chosen[1]["name"]


def test_system_context_bans_ai_openings():
    ctx = prompts.system_context(make_settings())
    assert "My team" in ctx  # listed as banned
    assert "Em-dashes" in ctx
