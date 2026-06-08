"""All user-facing Telegram copy (Hinglish), centralised.

Keeping presentation strings out of business logic makes the pipelines readable
and the wording editable in one place. Functions are used where a value is
interpolated; plain constants otherwise.
"""

from __future__ import annotations

DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def agent_starting(post_type: str) -> str:
    return (
        f"🤖 *LinkedIn Agent Starting* — {post_type.upper()} post\n\n"
        f"*30 seconds mein reply karo (optional):*\n"
        f"🔗 `/url <article/insta link>` — us pe post banao\n"
        f"💡 `/topic <idea>` — apna topic do\n\n"
        f"_Warna main khud topic choose kar leta hoon..._"
    )


def using_url(url: str) -> str:
    return f"🔗 Generating post from your article:\n_{url[:80]}_"


def using_topic(topic: str) -> str:
    return f"📌 Using your suggested topic:\n_{topic}_"


def using_queued_topic(title: str) -> str:
    return f"📅 Using this week's planned topic:\n_{title}_"


SKIPPED = "📭 Skipped. Next time!"
SKIPPED_POLL = "📭 Poll skipped."
SKIPPED_CAROUSEL = "📭 Carousel skipped."
SKIPPED_STORY = "📭 Story skipped."
PHOTO_RECEIVED = "📸 Photo mil gaya! Ab version select karo."


def pipeline_error(detail: str) -> str:
    return f"🔥 *Pipeline error:*\n`{detail[:300]}`"


def published(topic: str, url: str | None) -> str:
    link = url or "Check your LinkedIn feed"
    return (
        f"🎉 *Post published!*\n🔗 {link}\n\n"
        f"📌 _{topic[:80]}_"
    )


def poll_published(url: str | None) -> str:
    return f"🗳️ *Poll published!*\n🔗 {url or 'Check your LinkedIn feed'}"


def carousel_published(url: str | None) -> str:
    return f"📊 *Carousel published!*\n🔗 {url or 'Check your LinkedIn feed'}"


def publish_failed(error: str | None) -> str:
    return f"❌ Publish failed:\n`{error}`"


def first_comment_posted(comment: str) -> str:
    return f"💬 *First comment posted!*\n_{comment[:200]}_"


def scheduled_wait(hour: int, minute: int, wait_minutes: int) -> str:
    return (
        f"⏳ *Post Approved & Scheduled!*\n"
        f"Ideal posting time is *{hour:02d}:{minute:02d} AM IST*.\n"
        f"Bot will wait *{wait_minutes} minutes* before publishing to LinkedIn..."
    )


def performance_check(topic: str, url: str) -> str:
    url_line = f"🔗 {url}" if url else "🔗 Check your LinkedIn feed"
    return (
        f"📊 *Performance Check*\n{DIVIDER}\n"
        f"Your post from ~24h ago:\n📌 _{topic[:80]}_\n\n"
        f"{url_line}\n\nCheck likes, comments & impressions!"
    )


def weekly_report(this_week: int, total: int, last_post: str) -> str:
    last = last_post[:10] if last_post != "Never" else "Never"
    return (
        f"📊 *Weekly Report*\n{DIVIDER}\n"
        f"📝 This week: *{this_week}* posts\n"
        f"📈 Total ever: *{total}* posts\n"
        f"🕐 Last posted: *{last}*\n"
        f"{DIVIDER}\n✅ Agent running strong!"
    )


# ── Calendar planner ─────────────────────────────────────────
CALENDAR_PLANNING = (
    "📅 *Sunday Planning Mode*\n"
    "Generating this week's content calendar...\n"
    "_Give me ~30 seconds_"
)


def calendar_failed(detail: str) -> str:
    return f"❌ Calendar planning failed: `{detail[:200]}`"


def calendar_queued(topics: list[str]) -> str:
    return f"✅ *{len(topics)} topics queued for this week!*\n" + "\n".join(
        f"• {t[:70]}" for t in topics
    )
