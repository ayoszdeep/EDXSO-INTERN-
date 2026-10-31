# Automated Micro-Influencer Outreach System

EDXSO AI Engineer Intern, Assignment 1. The pipeline discovers real YouTube technology creators, filters and scores them, enriches their profiles, writes a personalized email and Instagram DM for each qualified creator, and sends (or simulates) the outreach with duplicate prevention and a log.

Demo campaign: **DevFlow AI** (a fictional AI coding assistant), targeting Software Development and AI/ML creators with 5K–100K subscribers. Everything is configurable in `config/campaign.json`.

## Technology stack
Python 3.10+, SQLite, yt-dlp, requests, python-dotenv, OpenAI SDK (optional), smtplib, pytest.

## APIs / tools used
- **yt-dlp**: reads public YouTube search, channel and video pages. No API key needed.
- **OpenAI Chat Completions** (`gpt-4o-mini`, optional): writes the messages if `OPENAI_API_KEY` is set.
- **SMTP** (Gmail App Password): real email sending. The default is simulation.
- **requests**: reads a creator's own website when they link one.

## Data sources
Public YouTube pages only: search results, channel About text and tags, and the 3 latest videos' views, likes, comments, dates and descriptions. Creator websites are read only if the creator links them. Nothing is hard-coded or estimated. Unavailable data is marked `Not Found`.

## Discovery methodology
29 search queries (AI agents, Python, FastAPI, LangChain, DevOps, ...) each run twice: by relevance and filtered to "uploaded this month", which surfaces smaller active creators. Two off-niche queries (smartphones, gaming) show the filter rejecting other niches. The uploader of each result is a candidate, deduplicated by channel ID, up to 200 channels. Results are throttled, retried and cached on disk.

## Filtering logic
Each channel gets **Qualified**, **Needs Review** or **Not Qualified**, with a written reason for every failed rule:
- Subscribers between 5,000 and 100,000
- Niche is Technology, sub-niche Software Development or AI & ML (keyword match on titles, tags and description)
- Recent videos match the target topics
- Engagement rate at least 1%, from `(likes + comments) / views` averaged over the 3 latest videos
- Last upload within 90 days

Missing evidence goes to Needs Review instead of passing or failing. A 0–100 brand-fit score (niche 25, content 25, size 15, engagement 25, activity 10) ranks the shortlist. Missing data scores 0.

## Enrichment process
Name, URL, subscribers, engagement, niche, themes and content style are computed from the collected data. **Email** is searched in the channel description, then recent video descriptions, then the creator's own website. It is checked for syntax and DNS, and its source URL is stored. If nothing is published, it is `Not Found`, and emails are never guessed. Instagram handle and website come from the creator's own links. Audience age, gender and geography are private YouTube analytics, so they are `Not Found (private analytics)`.

## AI model / prompt used
`gpt-4o-mini` with JSON output and the prompt in `prompts/outreach_prompt.txt`. It receives only real profile facts and is told never to invent videos, numbers, demographics or past relationships. Output outside the word limits gets one corrective retry. If the model still fails, or no key is set, the rule-based composer is used. Each message records which method wrote it.

## Personalization logic
Each message is built from the creator's own signals: a cleaned recent video title (never cut mid-phrase), content themes, content style (tutorial, project, review), real subscriber count and engagement. The collaboration angle is chosen from those signals:

| Signal | Angle |
|---|---|
| Under 15K subscribers | Affiliate + free access |
| Engagement 6% or more | Brand ambassador |
| Review channel | Paid review |
| Tutorial or project channel | Sponsored tutorial |
| Otherwise | Sponsored video / UGC |

Emails are 60–90 words and DMs 15–30 words. Messages that fail validation are marked `Invalid` and never sent.

## Sending mechanism
- **Review gate**: valid messages are auto-approved, or you can approve or reject them in `data/exports/review_decisions.csv`.
- **Email**: simulation by default. With `SENDING_MODE=real` it sends via SMTP. Because the brand is fictional, real mode is blocked unless `TEST_RECIPIENT_OVERRIDE` routes mail to your own inbox. Creators without a valid email are skipped.
- **Instagram DM**: not automated, because Instagram does not allow cold DMs through its API. DMs go to `data/exports/instagram_dm_queue.csv`. After sending by hand, run `python -m src.main --mark-dm-sent <influencer_id>`.
- **Duplicate prevention**: `UNIQUE(influencer_id, campaign_id, channel)` in SQLite. Anything already sent is never re-sent, and the same address is never emailed twice in a campaign.
- **Tracker**: `data/exports/outreach_log.csv`.

## Results of the included run
200 channels discovered, 55 in the 5K–100K range, **29 qualified**, 171 not qualified (each with a reason). 9 of the 29 had a published, validated email (the other 20 are `Not Found`) and 8 had an Instagram handle. 29 valid, distinct message sets were generated. 9 emails were simulated and 20 skipped. A second run re-sent nothing and blocked 17 duplicates.

Key files in `data/exports/`: `influencer_dataset.csv` (main dataset), `sample_messages.md` (readable emails and DMs), `outreach_log.csv`, `instagram_dm_queue.csv`, `run_summary.json`.

## Limitations
- yt-dlp reads public pages instead of the official YouTube Data API (no Google Cloud account or card needed). YouTube's terms restrict automated access, so volume is kept low. Use the official API for production.
- Engagement is derived from only the 3 latest videos, so one viral video can skew it.
- Only 9 of 29 qualified creators publish an email. YouTube hides the business-email button behind a CAPTCHA.
- Audience demographics are private and always `Not Found`.
- Niche detection is keyword-based and can misread ambiguous channels.
- Instagram handles are taken from creators' links and not verified. DMs are sent manually.
- The brand is fictional and no real email was sent. Real sending was not tested live.
- Data changes daily, so a re-run gives a slightly different dataset.

## Setup instructions
```bash
cd edxso-influencer-outreach
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # optional: add OPENAI_API_KEY / SMTP settings

python -m src.main              # full pipeline (about 8 minutes on the first run)
python -m src.main --discover   # or a single stage: --collect --filter --enrich
                                #   --personalize --validate --review --outreach --export
pytest -v                       # 33 offline tests
```
