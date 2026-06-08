"""LinkedIn client: URN building, payloads, response parsing."""

from __future__ import annotations

import pytest

from app.services.linkedin import client as api
from app.services.linkedin.client import LinkedInClient, LinkedInTokenExpiredError
from tests.conftest import FakeResponse, make_settings


def test_build_comment_url_encodes_urn_once():
    url = api.build_comment_url("urn:li:share:123")
    assert url == "https://api.linkedin.com/v2/socialActions/urn%3Ali%3Ashare%3A123/comments"
    assert ":" not in url.split("/socialActions/")[1].split("/")[0]  # colons fully encoded


def test_text_payload_shape():
    p = api.text_payload("urn:li:person:X", "hello")
    content = p["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert content["shareMediaCategory"] == "NONE"
    assert content["shareCommentary"]["text"] == "hello"
    assert p["author"] == "urn:li:person:X"


def test_image_payload_references_asset():
    p = api.image_payload("urn:li:person:X", "caption", "urn:li:digitalmediaAsset:A")
    media = p["specificContent"]["com.linkedin.ugc.ShareContent"]["media"][0]
    assert media["media"] == "urn:li:digitalmediaAsset:A"
    assert media["status"] == "READY"


def test_poll_payload_caps_options_and_length():
    p = api.poll_payload("urn:li:person:X", "txt", "Q?", ["a" * 50, "b", "c", "d", "e"])
    poll = p["specificContent"]["com.linkedin.ugc.ShareContent"]["media"][0]["poll"]
    assert len(poll["options"]) == 4  # capped at 4
    assert len(poll["options"][0]["text"]) == 30  # truncated to 30 chars


async def test_parse_response_success_builds_url():
    client = LinkedInClient(make_settings())
    resp = FakeResponse(201, headers={"X-RestLi-Id": "urn:li:share:99"})
    result = await client.parse_post_response(resp)
    assert result.success
    assert result.post_id == "urn:li:share:99"
    assert result.post_url.endswith("urn:li:share:99/")


async def test_parse_response_401_raises_token_expired():
    client = LinkedInClient(make_settings())
    with pytest.raises(LinkedInTokenExpiredError):
        await client.parse_post_response(FakeResponse(401))


async def test_parse_response_429_is_soft_failure():
    client = LinkedInClient(make_settings())
    result = await client.parse_post_response(FakeResponse(429))
    assert not result.success
    assert "Rate limit" in result.error


async def test_parse_response_other_error():
    client = LinkedInClient(make_settings())
    result = await client.parse_post_response(FakeResponse(400, body="bad request"))
    assert not result.success
    assert "HTTP 400" in result.error
