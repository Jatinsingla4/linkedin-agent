# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An autonomous LinkedIn content agent. It fetches trending topics → generates a post via Gemini → fetches an Unsplash image → sends a Telegram preview for human approval → publishes to LinkedIn. Runs on GitHub Actions on a cron schedule (Mon–Thu 9 AM IST, Sun 10:30 AM IST) or locally on demand. Post type varies by day: regular, personal story (Thu), poll (Sun), PDF carousel (Sat).

## Commands

```bash
# Install dependencies (Python 3.11+)
pip install -r requirements.txt

# Copy and fill in secrets before first run
cp .env.example .env

# One-time LinkedIn OAuth token setup
python -m entrypoints.get_linkedin_token

# Run the full pipeline locally (set DRY_RUN=true to skip publishing)
python -m entrypoints.run_agent

# Run the test suite
pytest
```

Logs are written to `agent.log` (appended, never overwritten) and stdout simultaneously.

## Required `.env` Variables

All 7 are required — startup raises `EnvironmentError` if any are missing or still set to `your_*` placeholders:

| Variable | Source |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com |
| `LINKEDIN_CLIENT_ID` | linkedin.com/developers |
| `LINKEDIN_CLIENT_SECRET` | linkedin.com/developers |
| `LINKEDIN_ACCESS_TOKEN` | Run `python -m entrypoints.get_linkedin_token` — expires every 60 days |
| `LINKEDIN_PERSON_URN` | Run `python -m entrypoints.get_linkedin_token` |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | @userinfobot on Telegram |
| `UNSPLASH_ACCESS_KEY` | unsplash.com/developers |

Optional config: `GEMINI_MODEL`, `POSTS_PER_WEEK`, `APPROVAL_TIMEOUT_HOURS`, `GENERATE_VERSIONS`, `ENABLE_FIRST_COMMENT`, `DRY_RUN`, `PERSONAL_STORY_DAY`/`POLL_DAY`/`CAROUSEL_DAY`, `YOUR_NAME`, `YOUR_ROLE`, `YOUR_COMPANY`, `YOUR_LINKEDIN_NICHE`.

## Architecture

Fully async (`asyncio`), organised as a layered `app/` package with thin executable `entrypoints/`. Each layer is independently testable; services receive `Settings` + a shared HTTP session via their constructors (dependency injection).

```
app/
  config.py            ← Settings dataclass; all env vars loaded & validated here
  models.py            ← shared dataclasses + PostType enum (typed boundaries)
  strings.py           ← all user-facing Telegram copy
  logging_config.py    ← single setup_logging()
  core/
    http.py            ← aiohttp session factory with VERIFIED TLS (certifi)
    state.py           ← StateStore: single owner of agent_state.json, atomic writes
    scheduler.py       ← post_type_for_day(), wait_for_ideal_time() (IST, zoneinfo)
    lock.py            ← single-instance file lock (prevents Telegram 409 double-runs)
  services/
    gemini_client.py   ← model config + quota fallback + JSON parsing
    topic_engine.py    ← RSS + Reddit → ranked Topic list (fallback list if all fail)
    image_fetcher.py   ← Unsplash → temp file (picsum fallback)
    pdf_generator.py   ← carousel PDF via reportlab
    content/{writer,prompts}.py  ← ContentWriter + prompt templates / POST_FORMATS
    telegram_bot.py    ← ApprovalBot: previews, getUpdates polling, typed VersionSelection
    linkedin/{client,publisher}.py ← low-level UGC API + high-level publish flows
  pipelines/
    base.py            ← BasePipeline: publish+record+notify, first comment, article fetch
    regular.py / story.py / poll.py / carousel.py
  reporting.py         ← performance reminders + weekly report
  orchestrator.py      ← thin: resolve topic, pick pipeline by day, run

entrypoints/           ← run_agent, plan_calendar, performance_check, get_linkedin_token
tests/                 ← pytest suite (no network; all I/O mocked)
```

**State persistence**: `StateStore` owns `agent_state.json` (used topics capped at 50, recent posts at 10, content queue). Writes are atomic (temp file + rename).

**Topic scoring**: niche keyword matches + `rss` source bonus. All sources failing → hardcoded evergreen fallback.

**Approval flow**: long-polling (`getUpdates`), no public server needed. Waits up to `APPROVAL_TIMEOUT_HOURS` (default 12h). On Telegram send failure the run aborts (does NOT auto-publish).

**Content generation**: `ContentWriter` rotates 8 post formats (hot take, observation, mistake, etc.) so posts don't look AI-generated; persona comes from `YOUR_NAME`/`YOUR_ROLE`/`YOUR_COMPANY`/`YOUR_LINKEDIN_NICHE`.

## Customisation Points

- **Posting schedule**: cron in `.github/workflows/linkedin_agent.yml`
- **Writing persona**: `YOUR_*` env vars
- **Topic sources**: `RSS_FEEDS` / `REDDIT_SUBREDDITS` in `app/services/topic_engine.py`
- **Post formats**: `POST_FORMATS` in `app/services/content/prompts.py`
- **Gemini model**: `GEMINI_MODEL` env var (default `gemini-2.5-flash`; the 2.0-flash family is retired)

## GitHub Actions Deployment

Push to a **private** repo. Add all 8 required secrets under Settings → Secrets and variables → Actions. The workflow runs automatically on schedule and can be triggered manually via the Actions UI (with optional `dry_run` input).

The Actions job has a 60-minute timeout to accommodate the approval wait window.
