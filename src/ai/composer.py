# src/ai/composer.py
"""Rule-based message composer (used when no LLM key is configured, or the LLM fails).

Unlike a fixed template, each message is assembled from the creator's own signals:
  - the most campaign-relevant recent video title (cleaned, never cut mid-phrase)
  - content themes and dominant content style (tutorial / review / project build ...)
  - real subscriber count and measured engagement rate
  - a collaboration angle chosen from those signals (affiliate, ambassador, review, ...)
Sentence variants are picked deterministically per creator so wording differs across
creators but stays reproducible between runs.
"""
import hashlib
import re
from itertools import product
from typing import Any, Dict, List, Optional, Tuple

from src.ai.message_validator import DM_RANGE, EMAIL_RANGE, count_words
from src.processing.content_analysis import SUB_NICHES, count_keyword_hits

CHANNEL_WORDS = {"code", "codes", "coding", "tech", "dev", "devs", "ai", "academy", "tutorials", "labs",
                 "lab", "hub", "tv", "official", "channel", "studio", "media", "learn", "learning",
                 "programming", "school", "with", "the", "and", "io", "data", "python", "digital"}

ACRONYMS = {"AI", "API", "LLM", "LLMS", "RAG", "ML", "UI", "UX", "AWS", "GPT", "SQL", "CSS", "HTML", "JS", "IDE", "CLI", "MCP"}

AUDIENCE = {
    "AI & Machine Learning": "developers building with AI",
    "Software Development": "working developers and people learning to code",
}

STYLE_PHRASES = {
    "tutorial": ["walk viewers through {theme} step by step", "turn {theme} into practical, follow-along lessons"],
    "project build": ["build real {theme} projects on camera", "show {theme} through hands-on builds"],
    "review": ["compare options in {theme} side by side for your viewers", "give practical, honest verdicts on {theme}"],
    "news & commentary": ["keep developers current on {theme}", "break down what is new in {theme}"],
    "general": ["cover {theme} for developers", "focus on {theme}"],
}

ANGLES = {
    "affiliate": ("Affiliate campaign + free Pro access",
                  "We would like to give you free Pro access plus a 30% affiliate commission and a custom discount code for your viewers.",
                  "an affiliate partnership"),
    "ambassador": ("Brand ambassador program",
                   "Given how engaged your community is, we would love to discuss a paid three-month ambassador partnership with early feature access.",
                   "a paid ambassador partnership"),
    "review": ("Paid product review",
               "We would like to offer a paid review slot: you test {brand} on your own projects and share your honest verdict.",
               "a paid, honest review"),
    "tutorial": ("Sponsored tutorial integration",
                 "We would love to sponsor an upcoming video where you use {brand} in a real {theme} project, in your own style.",
                 "a sponsored tutorial integration"),
    "dedicated": ("Sponsored dedicated video",
                  "We would love to sponsor a dedicated video or a short UGC piece showing {brand} in your everyday workflow.",
                  "a sponsored video"),
}

OPENERS = [
    'Hi {g}, I watched your recent video "{t}" and liked how you {style}.',
    'Hi {g}, your recent upload "{t}" caught my eye because you {style}.',
    'Hi {g}, I came across "{t}" while looking for creators who {style}.',
]
OPENERS_NO_TITLE = [
    "Hi {g}, I have been going through your recent uploads, where you {style}.",
    "Hi {g}, I found your channel while looking for creators who {style}.",
]
AUDIENCE_LINES = [
    "With {subs} subscribers and around {eng}% engagement on recent videos, your channel reaches the {aud} that our product is built for.",
    "Your recent uploads average {eng}% engagement across {subs} subscribers, which tells us your community of {aud} really listens.",
]
AUDIENCE_LINES_NO_ENG = [
    "Your {subs}-subscriber channel reaches the {aud} that our product is built for.",
]
THEME_LINES = [
    "Topics like {themes} line up closely with what our users ask for.",
    "Your focus on {themes} matches the problems our product solves.",
]
CTAS = [
    "Would you be open to a quick chat this week?",
    "Could I send over a short brief with budget and timelines?",
    "If this sounds interesting, I would be happy to share details and rates.",
]
DM_TEMPLATES = [
    'Hi {g}! Really liked "{t}". We are {brand}, {product}, and think {angle} with you could fit well. Open to a chat?',
    'Hey {g}, your video "{t}" was great. I am reaching out from {brand} about {angle}. Could I send details?',
]
DM_TEMPLATES_NO_TITLE = [
    "Hi {g}! Your {theme} videos are a great fit for {brand}, {product}. Would you be open to {angle}?",
    "Hey {g}, love your {theme} content. We are {brand} and would like to explore {angle}. Open to chat?",
]


def _pick(options: List[str], seed: str, salt: str) -> str:
    idx = int(hashlib.md5(f"{seed}:{salt}".encode()).hexdigest(), 16) % len(options)
    return options[idx]


def clean_channel_name(name: str) -> str:
    """Drop taglines and decorations: '@Jane Doe - ML Engineer | Tutorials' -> 'Jane Doe'."""
    core = re.split(r"\s[-–—|•:]\s|\s\(", name or "")[0]
    return core.strip().lstrip("@").strip() or (name or "").strip()


def greeting_name(name: str) -> str:
    """First name if the channel name looks like a person ('Jane Doe'), else the channel name."""
    name = clean_channel_name(name)
    words = name.split()
    if 2 <= len(words) <= 3 and all(w.isalpha() and w[0].isupper() for w in words) \
            and not any(w.lower() in CHANNEL_WORDS for w in words):
        return words[0]
    return name


def clean_title(title: str, max_words: int = 9) -> Optional[str]:
    """Readable short form of a video title, or None if it can't be shortened cleanly."""
    if not title:
        return None
    t = re.sub(r"#\w+", "", title)                      # hashtags
    t = re.split(r"\s[|•]\s|\s[-–—]\s|\s\(|\s\[", t)[0]  # drop subtitle after | - ( [
    t = re.sub(r"[^\w\s.,:'&+/?!-]", " ", t)           # emojis / decorative symbols
    t = re.sub(r"\s+", " ", t).strip(" -:,.")
    if t.isupper():
        t = " ".join(w if w in ACRONYMS else w.title() for w in t.split())
    words = t.split()
    if len(words) > max_words and ":" in t:
        t = t.split(":")[0].strip()
        words = t.split()
    if not words or len(words) > max_words or not t.isascii():
        return None
    return t


def best_title(videos: List[Dict[str, Any]], target_sub_niches: List[str]) -> Optional[str]:
    """Most campaign-relevant recent title that can be quoted cleanly."""
    keywords = [kw for sub in target_sub_niches for kw in SUB_NICHES.get(sub, ("", []))[1]]
    ranked = sorted(videos, key=lambda v: -sum(count_keyword_hits(v.get("title") or "", keywords).values()))
    for v in ranked:
        cleaned = clean_title(v.get("title") or "")
        if cleaned:
            return cleaned
    return None


def choose_angle(followers: int, engagement: Optional[float], style: str) -> str:
    if followers < 15000:
        return "affiliate"
    if engagement is not None and engagement >= 6:
        return "ambassador"
    if style == "review":
        return "review"
    if style in ("tutorial", "project build"):
        return "tutorial"
    return "dedicated"


def format_subs(n: int) -> str:
    return f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else str(n)


def compose_messages(profile: Dict[str, Any], brand: Dict[str, Any],
                     target_sub_niches: List[str]) -> Dict[str, Any]:
    seed = profile["influencer_id"]
    g = greeting_name(profile["name"])
    themes: List[str] = [t for t in profile.get("content_themes", [])
                         if t and t != "general technology"] or ["developer tools"]
    theme = themes[0]
    style = profile.get("content_style") or "general"
    title = best_title(profile.get("recent_content", []), target_sub_niches)
    followers = profile.get("follower_count") or 0
    engagement = profile.get("engagement_rate")
    angle_key = choose_angle(followers, engagement, style)
    angle_label, angle_sentence, angle_short = ANGLES[angle_key]
    fmt = {
        "g": g, "t": title, "theme": theme, "brand": brand["name"],
        "product": brand.get("product_short", brand["product"]),
        "subs": format_subs(followers), "eng": engagement,
        "aud": AUDIENCE.get(profile.get("sub_niche"), "developers"),
        "themes": " and ".join(themes[:2]), "angle": angle_short,
    }
    fmt["style"] = _pick(STYLE_PHRASES.get(style, STYLE_PHRASES["general"]), seed, "style").format(**fmt)

    opener = _pick(OPENERS if title else OPENERS_NO_TITLE, seed, "open").format(**fmt)
    audience = _pick(AUDIENCE_LINES if engagement is not None else AUDIENCE_LINES_NO_ENG,
                     seed, "aud").format(**fmt)
    product_line = f"{brand['name']} is {brand['product']}."
    theme_line = _pick(THEME_LINES, seed, "theme").format(**fmt)
    angle_line = angle_sentence.format(**fmt)
    cta = _pick(CTAS, seed, "cta")

    # Try sentence combinations from richest to leanest until the email fits 60-90 words.
    email_body = None
    # Prefer keeping the audience line (real numbers) over the generic theme line.
    for use_audience, use_theme in product([True, False], [True, False]):
        parts = [opener, audience if use_audience else None, product_line,
                 theme_line if use_theme else None, angle_line, cta]
        body = " ".join(p for p in parts if p)
        if EMAIL_RANGE[0] <= count_words(body) <= EMAIL_RANGE[1]:
            email_body = body
            break
    if email_body is None:
        email_body = " ".join([opener, audience, product_line, theme_line, angle_line, cta])

    dm = None
    templates = ([_pick(DM_TEMPLATES, seed, "dm")] if title else []) + [_pick(DM_TEMPLATES_NO_TITLE, seed, "dm2")]
    for tpl in templates:
        candidate = tpl.format(**fmt)
        if DM_RANGE[0] <= count_words(candidate) <= DM_RANGE[1]:
            dm = candidate
            break
    dm = dm or templates[-1].format(**fmt)

    subject = _pick([
        "{brand} x {name}: {angle_label}",
        "Partnership idea for {name}: {angle_label}",
        "{name} + {brand}: {angle_label}?",
    ], seed, "subj").format(brand=brand["name"], name=clean_channel_name(profile["name"]), angle_label=angle_label)

    signals = [f"video: \"{title}\"" if title else "no quotable recent title",
               f"themes: {', '.join(themes)}", f"style: {style}", f"{format_subs(followers)} subscribers"]
    if engagement is not None:
        signals.append(f"{engagement}% engagement")
    signals.append(f"angle: {angle_label}")

    return {
        "email_subject": subject,
        "email_body": email_body,
        "instagram_dm": dm,
        "personalization_signals": "; ".join(signals),
        "collaboration_type": angle_label,
    }
