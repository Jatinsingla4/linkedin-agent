# 🤖 LinkedIn AI Agent

Automatically generates and posts LinkedIn content on your behalf using **Gemini AI** (free) + **Unsplash** (free) + **LinkedIn Official API** (free).

**Total cost: $0/month**

---

## How It Works

```
Every Mon/Wed/Fri/Sun at 9 AM IST
         ↓
Fetch trending topics (RSS + Reddit)
         ↓
Gemini writes post in your voice
         ↓
Unsplash finds the perfect image
         ↓
Telegram sends you a preview
         ↓
You tap ✅ to post or ❌ to skip
         ↓
Posts live on LinkedIn
```

---

## Setup Guide (One Time)

### Step 1 — Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/linkedin-agent.git
cd linkedin-agent
pip install -r requirements.txt
cp .env.example .env
```

---

### Step 2 — Get Gemini API Key (2 min)

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **"Get API Key"** → **"Create API key"**
3. Copy the key → paste into `.env`:
   ```
   GEMINI_API_KEY=AIzaSy...
   ```

---

### Step 3 — Get Unsplash API Key (3 min)

1. Go to [unsplash.com/developers](https://unsplash.com/developers)
2. Click **"Register as a developer"**
3. Create a new app (name it "LinkedIn Agent")
4. Copy **Access Key** → paste into `.env`:
   ```
   UNSPLASH_ACCESS_KEY=your_access_key
   ```

---

### Step 4 — Create LinkedIn Developer App (10 min)

1. Go to [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps)
2. Click **"Create App"**
3. Fill in:
   - App name: `LinkedIn Agent`
   - LinkedIn Page: your personal or company page
   - App logo: any image
4. Go to **"Auth"** tab → copy **Client ID** and **Client Secret**
5. Add this redirect URL: `https://localhost:8000/callback`
6. Go to **"Products"** tab → request **"Share on LinkedIn"** (instant approval)
7. Paste into `.env`:
   ```
   LINKEDIN_CLIENT_ID=your_client_id
   LINKEDIN_CLIENT_SECRET=your_client_secret
   ```

**Now get your Access Token:**
```bash
python -m entrypoints.get_linkedin_token
```
Follow the prompts — it will print your `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_PERSON_URN`.
Paste both into `.env`.

> ⚠️ LinkedIn tokens expire in **60 days**. Re-run the token helper when it expires.

---

### Step 5 — Create Telegram Bot (3 min)

1. Open Telegram → search for **@BotFather**
2. Send: `/newbot`
3. Follow prompts → copy the **token** → paste into `.env`:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
   ```

**Get your Chat ID:**
1. Search for **@userinfobot** on Telegram
2. Send it any message → it replies with your Chat ID
3. Paste into `.env`:
   ```
   TELEGRAM_CHAT_ID=123456789
   ```

---

### Step 6 — Test Locally

```bash
python -m entrypoints.run_agent      # run the full pipeline
pytest                               # run the test suite
```

You should receive a Telegram message with a post preview. Tap ✅ — it will post to LinkedIn.

> Tip: set `DRY_RUN=true` in `.env` to run the whole flow without actually publishing to LinkedIn.

---

### Step 7 — Deploy to GitHub Actions (Free, runs forever)

1. Push your code to a **private GitHub repo**:
   ```bash
   git init
   git add .
   git commit -m "Initial LinkedIn agent"
   git remote add origin https://github.com/YOUR_USERNAME/linkedin-agent.git
   git push -u origin main
   ```

2. Add secrets to GitHub:
   - Go to your repo → **Settings** → **Secrets and variables** → **Actions**
   - Click **"New repository secret"** for each:

   | Secret Name | Where to find it |
   |---|---|
   | `GEMINI_API_KEY` | Google AI Studio |
   | `LINKEDIN_CLIENT_ID` | LinkedIn Developer App |
   | `LINKEDIN_CLIENT_SECRET` | LinkedIn Developer App |
   | `LINKEDIN_ACCESS_TOKEN` | Output of `python -m entrypoints.get_linkedin_token` |
   | `LINKEDIN_PERSON_URN` | Output of `python -m entrypoints.get_linkedin_token` |
   | `TELEGRAM_BOT_TOKEN` | @BotFather |
   | `TELEGRAM_CHAT_ID` | @userinfobot |
   | `UNSPLASH_ACCESS_KEY` | Unsplash developers |

3. That's it. The agent runs automatically on schedule.

---

## Customisation

### Change posting schedule
Edit `.github/workflows/linkedin_agent.yml`:
```yaml
- cron: "30 3 * * 1,3,5,0"   # Mon, Wed, Fri, Sun at 9 AM IST
```
Use [crontab.guru](https://crontab.guru) to customise.

### Change topics / niche
In `.github/workflows/linkedin_agent.yml` or your `.env`:
```
YOUR_LINKEDIN_NICHE=marketing,branding,AI,FMCG,agency life,startup
```

### Run manually anytime
Go to your GitHub repo → **Actions** → **LinkedIn Agent** → **Run workflow**

---

## Telegram Commands

When you receive a post preview:

| Command | Action |
|---|---|
| Tap **✅ Post it** | Post immediately |
| Tap **❌ Skip** | Skip this post |
| `/edit Your new post text here` | Replace text and post |
| ✅ (emoji in chat) | Post immediately |
| ❌ (emoji in chat) | Skip |

---

## File Structure

```
linkedin-agent/
├── app/                          # importable package
│   ├── config.py                 # Settings + env validation
│   ├── models.py                 # shared dataclasses & enums
│   ├── strings.py                # all Telegram copy
│   ├── logging_config.py
│   ├── core/                     # http (verified SSL), state store, scheduler, lock
│   ├── services/                 # gemini, topics, images, pdf, telegram, linkedin/
│   ├── pipelines/                # base + regular / story / poll / carousel
│   ├── reporting.py              # performance reminders + weekly report
│   └── orchestrator.py           # thin coordinator (routes by day)
├── entrypoints/                  # python -m entrypoints.<name>
│   ├── run_agent.py              # the posting pipeline
│   ├── plan_calendar.py          # Sunday content planner
│   ├── performance_check.py
│   └── get_linkedin_token.py
├── tests/                        # pytest suite (no network)
├── requirements.txt
├── pyproject.toml                # pytest + ruff config
├── .env.example
└── .github/workflows/            # schedules + watchdog
```

---

## Troubleshooting

**"LinkedIn token expired"**
→ Run `python -m entrypoints.get_linkedin_token` and update `LINKEDIN_ACCESS_TOKEN` in GitHub Secrets

**"Telegram preview not received"**
→ Check `TELEGRAM_CHAT_ID` — send a message to your bot first to activate it

**"Unsplash 403 error"**
→ Check `UNSPLASH_ACCESS_KEY` — ensure your app is in "Demo" mode on Unsplash

**"Gemini quota exceeded"**
→ Very unlikely at 4 posts/week. If it happens, wait until next day (free quota resets daily)

---

## Security Notes

- `.env` is in `.gitignore` — your secrets never get committed
- GitHub Actions secrets are encrypted at rest
- No third-party services have access to your LinkedIn credentials
- The agent only posts — it never reads your messages or connections
