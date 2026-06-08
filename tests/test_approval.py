"""ApprovalBot command parsing + VersionSelection model semantics."""

from __future__ import annotations

from app.models import NEWTOPIC_PREFIX, URL_PREFIX, GeneratedPost, VersionSelection
from app.services.telegram_bot import ApprovalBot
from tests.conftest import make_settings


def _post(text: str = "full text") -> GeneratedPost:
    return GeneratedPost(
        topic="t", hook="h", body="b", cta="c", hashtags=["#x"],
        image_query="q", full_text=text, word_count=2,
    )


# ── VersionSelection model ───────────────────────────────────

def test_selection_skipped():
    assert VersionSelection().skipped is True
    assert VersionSelection(selected_post=_post()).skipped is False


def test_selection_newtopic_and_url():
    nt = VersionSelection(edited_text=NEWTOPIC_PREFIX + "AI ethics")
    assert nt.newtopic == "AI ethics"
    assert nt.url is None

    u = VersionSelection(edited_text=URL_PREFIX + "http://x.com")
    assert u.url == "http://x.com"
    assert u.newtopic is None


# ── Command matching ─────────────────────────────────────────

def bot() -> ApprovalBot:
    return ApprovalBot(make_settings())


def test_match_newtopic():
    sel = bot()._match_command("/newtopic What is MCP?", [_post()], None)
    assert sel.newtopic == "What is MCP?"


def test_match_url_requires_http():
    assert bot()._match_command("/url not-a-link", [_post()], None) is None
    sel = bot()._match_command("/url https://x.com/a", [_post()], None)
    assert sel.url == "https://x.com/a"


def test_match_edit_returns_text():
    sel = bot()._match_command("/edit my own post text", [_post()], None)
    assert sel.edited_text == "my own post text"
    assert sel.newtopic is None and sel.url is None


def test_match_plain_text_is_not_a_command():
    assert bot()._match_command("just chatting", [_post()], None) is None


def test_escape_markdown():
    assert ApprovalBot._escape("a_b*c`d[e") == r"a\_b\*c\`d\[e"
