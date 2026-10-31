# src/enrichment/contact_extractor.py
"""Extract contact details that creators publish themselves (channel About text,
video descriptions, their own website). Nothing is guessed or pattern-generated.
"""
import re
from collections import Counter
from typing import List, Optional
from urllib.parse import urlparse

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
# Common obfuscations: name [at] domain [dot] com, name(at)domain(dot)com
_OBFUSCATED_AT = re.compile(r"\s*[\[(\{]\s*at\s*[\])\}]\s*", re.IGNORECASE)
_OBFUSCATED_DOT = re.compile(r"\s*[\[(\{]\s*dot\s*[\])\}]\s*", re.IGNORECASE)

IGNORED_EMAIL_DOMAINS = {"example.com", "domain.com", "email.com", "sentry.io", "wixpress.com",
                         "sentry.wixpress.com", "yourdomain.com", "test.com"}
IGNORED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
IGNORED_EMAIL_PREFIXES = ("noreply", "no-reply", "donotreply", "privacy", "abuse", "legal")

INSTAGRAM_PATTERN = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.IGNORECASE)
INSTAGRAM_RESERVED = {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "direct"}

URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
# Domains that are never "the creator's own website".
NON_WEBSITE_DOMAINS = (
    "youtube.com", "youtu.be", "instagram.com", "twitter.com", "x.com", "facebook.com", "fb.com",
    "tiktok.com", "linkedin.com", "discord.gg", "discord.com", "t.me", "telegram.me", "github.com",
    "twitch.tv", "reddit.com", "amzn.to", "amazon.", "bit.ly", "goo.gl", "tinyurl.com", "geni.us",
    "patreon.com", "buymeacoffee.com", "ko-fi.com", "paypal.", "spotify.com", "apple.com",
    "google.com", "forms.gle", "whatsapp.com", "wa.me", "threads.net", "medium.com",
    "udemy.com", "coursera.org", "skillshare.com", "shopify.com", "envato", "nordvpn", "hostinger",
)


def deobfuscate(text: str) -> str:
    return _OBFUSCATED_DOT.sub(".", _OBFUSCATED_AT.sub("@", text or ""))


def extract_emails(text: str) -> List[str]:
    """All plausible emails in text, lower-cased, in order of first appearance."""
    found: List[str] = []
    for raw in EMAIL_PATTERN.findall(deobfuscate(text)):
        email = raw.strip(".").lower()
        domain = email.split("@", 1)[1]
        if (domain in IGNORED_EMAIL_DOMAINS or email.endswith(IGNORED_EMAIL_SUFFIXES)
                or email.startswith(IGNORED_EMAIL_PREFIXES)):
            continue
        if email not in found:
            found.append(email)
    return found


def pick_business_email(emails: List[str]) -> Optional[str]:
    """Prefer addresses that look like business/collab inboxes."""
    if not emails:
        return None
    preferred = ("business", "collab", "partner", "sponsor", "brand", "contact", "hello", "media", "work")
    for email in emails:
        if email.split("@")[0].startswith(preferred):
            return email
    return emails[0]


def extract_instagram(texts: List[str]) -> Optional[str]:
    """Most frequently linked Instagram handle across the given texts."""
    counts: Counter = Counter()
    for text in texts:
        for handle in INSTAGRAM_PATTERN.findall(text or ""):
            handle = handle.rstrip(".").lower()
            if handle not in INSTAGRAM_RESERVED:
                counts[handle] += 1
    return counts.most_common(1)[0][0] if counts else None


def extract_website(text: str) -> Optional[str]:
    """First URL in text that is not a social network, store or link shortener."""
    for url in URL_PATTERN.findall(text or ""):
        url = url.rstrip(".,;")
        host = urlparse(url).netloc.lower()
        if host and not any(d in host for d in NON_WEBSITE_DOMAINS):
            return url
    return None
