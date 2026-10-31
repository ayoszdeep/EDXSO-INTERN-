# Automated Micro-Influencer Outreach System

Finds real YouTube tech creators (5K–100K subscribers), filters and scores them, finds their published contact details, writes a personalized email and Instagram DM for each qualified creator, and sends (or simulates) the outreach without duplicates. The demo brand is "DevFlow AI" (fictional). Run result: 200 channels found, 29 qualified.

## Technology stack
Python 3.10+, SQLite, yt-dlp, requests, OpenAI SDK (optional), smtplib, Streamlit, pytest.

## APIs / tools used
- **yt-dlp**: reads public YouTube pages (no API key needed)
- **OpenAI** (`gpt-4o-mini`, optional): writes messages
- **SMTP / Gmail**: real sending (off by default)

## Data sources
Public YouTube pages: search results, channel About text, and each channel's 3 latest videos (views, likes, comments, dates, descriptions). A creator's own website is read only if they link it. Anything unavailable is marked `Not Found`.

## Discovery methodology
29 search queries (Python, AI agents, FastAPI, DevOps...) are run twice each: by relevance and "uploaded this month". Each result's channel is kept once, deduplicated by channel ID, up to 200 channels. Two off-niche queries (phones, gaming) show the filter rejecting other niches.

## Filtering logic
Each channel is **Qualified**, **Needs Review** or **Not Qualified**, with a written reason. Rules:
- 5,000–100,000 subscribers
- Software Development or AI/ML niche, matched by keywords in titles, tags and description
- Recent videos match the target topics
- Engagement at least 1%: (likes + comments) / views, averaged over the 3 latest videos
- Uploaded within the last 90 days

Missing data goes to Needs Review. A 0–100 brand-fit score ranks the qualified list.

## Enrichment process
Subscribers, engagement, niche and themes come from the collected data. **Email** is searched in the channel description, then video descriptions, then the creator's own site. It is checked for syntax and DNS, and its source URL is saved. If none is published it says `Not Found`; emails are never guessed. Instagram and website come from the creator's own links. Audience age, gender and geography are private on YouTube, so they are `Not Found`.

## AI model / prompt used
`gpt-4o-mini` with the prompt in `prompts/outreach_prompt.txt`. It gets only real profile facts and must not invent videos, numbers or past relationships. Output outside the word limits is retried once. **Without an OpenAI key (as in the included dataset), a built-in rule-based writer is used instead.** The LLM path is built but was not run live.

## Personalization logic
Each message uses the creator's own cleaned recent video title, themes, content style, subscriber count and engagement. The collaboration type depends on those signals: under 15K subscribers gets an affiliate offer, 6%+ engagement a brand ambassador deal, review channels a paid review, and tutorial channels a sponsored tutorial. Emails are 60–90 words and DMs 15–30 words. Messages outside those limits are never sent.

## Sending mechanism
- **Email:** simulation by default. `SENDING_MODE=real` sends via SMTP, but is blocked for the fictional brand unless `TEST_RECIPIENT_OVERRIDE` sends it to your own inbox. Creators with no email are skipped.
- **Instagram DM:** not automated (Instagram doesn't allow cold DMs via API). DMs are listed in `data/exports/instagram_dm_queue.csv` to send by hand.
- **Duplicates:** SQLite `UNIQUE(influencer_id, campaign_id, channel)`. A second run re-sends nothing.
- **Log:** `data/exports/outreach_log.csv`.

Main outputs are in `data/exports/`: `influencer_dataset.csv`, `sample_messages.md`, `outreach_log.csv`, `run_summary.json`.

## Limitations
- yt-dlp reads public pages instead of the official YouTube API. Use the API for production.
- Engagement uses only 3 videos, so one viral video can skew it.
- Only 9 of 29 qualified creators publish an email. The other 20 are `Not Found`.
- Audience demographics are unavailable.
- Niche detection is keyword-based and can misread some channels.
- Instagram handles are not verified. Real email sending was not tested live.

## Setup instructions
```bash
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # optional: add OPENAI_API_KEY / SMTP settings

python -m src.main               # run everything (about 8 min the first time)
streamlit run src/dashboard.py   # web dashboard
pytest -v                        # tests
```
