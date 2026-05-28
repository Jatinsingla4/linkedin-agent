# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An autonomous LinkedIn content agent. It fetches trending topics → generates a post via Gemini → fetches an Unsplash image → sends a Telegram preview for human approval → publishes to LinkedIn. Runs on GitHub Actions on a cron schedule (Mon/Wed/Fri/Sun 9 AM IST) or locally on demand.

## Commands

```bash
# Install dependencies (Python 3.12)
pip install -r requirements.txt

# Copy and fill in secrets before first run
cp .env.example .env   # (if .env.example exists) or edit .env directly

# One-time LinkedIn OAuth token setup
python get_linkedin_token.py

# Run the full pipeline locally
python orchestrator.py
```

Logs are written to `agent.log` (appended, never overwritten) and stdout simultaneously.

## Required `.env` Variables

All 7 are required — startup raises `EnvironmentError` if any are missing or still set to `your_*` placeholders:

| Variable | Source |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com |
| `LINKEDIN_CLIENT_ID` | linkedin.com/developers |
| `LINKEDIN_CLIENT_SECRET` | linkedin.com/developers |
| `LINKEDIN_ACCESS_TOKEN` | Run `get_linkedin_token.py` — expires every 60 days |
| `LINKEDIN_PERSON_URN` | Run `get_linkedin_token.py` |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | @userinfobot on Telegram |
| `UNSPLASH_ACCESS_KEY` | unsplash.com/developers |

Optional config: `POSTS_PER_WEEK`, `APPROVAL_TIMEOUT_HOURS`, `YOUR_NAME`, `YOUR_ROLE`, `YOUR_COMPANY`, `YOUR_LINKEDIN_NICHE` (comma-separated keywords).

## Architecture

The pipeline is fully async (`asyncio`). `orchestrator.py` coordinates five independent modules — each can be developed/tested in isolation:

```
orchestrator.py
  ├── config/settings.py          ← Singleton Config dataclass; all env vars loaded here
  ├── src/topic_engine.py         ← RSS feeds + Reddit JSON API → ranked Topic list
  ├── src/content_writer.py       ← Gemini 2.0 Flash → structured GeneratedPost (JSON prompt)
  ├── src/image_fetcher.py        ← Unsplash API → temp image file
  ├── src/approval_bot.py         ← Telegram bot: sends preview, polls getUpdates for response
  └── src/linkedin_publisher.py   ← LinkedIn UGC API v2: text-only or with image upload
```

**State persistence**: `agent_state.json` tracks used topic titles (last 50) to avoid repeats across runs. Auto-created if missing.

**Topic scoring**: Topics are scored by niche keyword matches + source (`rss` gets +1). If all RSS/Reddit sources fail, `TopicEngine` falls back to a hardcoded evergreen list.

**Approval flow**: `approval_bot.py` uses long-polling (`getUpdates`) rather than webhooks — works without a public server. The bot waits up to `APPROVAL_TIMEOUT_HOURS` (default 12h), checking every 5 seconds. On Telegram failure, it auto-approves rather than blocking the pipeline.

**Content generation**: `ContentWriter` sends a structured JSON-schema prompt to Gemini and parses the response. The system context is built from `YOUR_NAME`, `YOUR_ROLE`, `YOUR_COMPANY`, and `YOUR_LINKEDIN_NICHE` — changing these env vars changes the AI's writing persona entirely.

## Customisation Points

- **Posting schedule**: edit the cron in `.github/workflows/linkedin_agent.yml`
- **Writing persona**: change `YOUR_NAME`, `YOUR_ROLE`, `YOUR_COMPANY`, `YOUR_LINKEDIN_NICHE` in `.env`
- **Topic sources**: add RSS feeds to `RSS_FEEDS` or subreddits to `REDDIT_SUBREDDITS` in `src/topic_engine.py`
- **Gemini model**: `gemini_model` field in `config/settings.py` (currently `gemini-2.0-flash`)

## GitHub Actions Deployment

Push to a **private** repo. Add all 8 required secrets under Settings → Secrets and variables → Actions. The workflow runs automatically on schedule and can be triggered manually via the Actions UI (with optional `dry_run` input).

The Actions job has a 60-minute timeout to accommodate the approval wait window.
