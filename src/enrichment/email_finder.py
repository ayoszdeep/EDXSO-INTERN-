# src/enrichment/email_finder.py
"""Find and validate a creator's business email.
Search order (stops at first hit):
  1. YouTube channel About description
  2. Descriptions of the creator's recent videos
  3. The creator's own website (homepage + /contact), only for shortlisted creators
Validation: syntax check + DNS resolution of the email domain.
If nothing is published, the email is 'Not Found'. Emails are never guessed.
"""
import logging
import re
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from src.enrichment.contact_extractor import extract_emails, pick_business_email

LOGGER = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$")
_DOMAIN_CACHE: Dict[str, bool] = {}
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (influencer-outreach research prototype)"}

NOT_FOUND = {"email": "Not Found", "email_source": "Not Found",
             "email_source_url": "Not Found", "email_validation_status": "unavailable"}


def validate_email_syntax(email: Optional[str]) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def check_domain_resolution(domain: str) -> bool:
    """True if the email domain resolves in DNS (cached)."""
    domain = domain.strip().lower()
    if domain not in _DOMAIN_CACHE:
        try:
            socket.getaddrinfo(domain, None)
            _DOMAIN_CACHE[domain] = True
        except (socket.gaierror, socket.herror, UnicodeError, OSError):
            _DOMAIN_CACHE[domain] = False
    return _DOMAIN_CACHE[domain]


def validate_email(email: str) -> str:
    """'valid', 'syntax_error' or 'domain_unreachable'."""
    if not validate_email_syntax(email):
        return "syntax_error"
    return "valid" if check_domain_resolution(email.split("@")[1]) else "domain_unreachable"


def fetch_website_emails(website: str, timeout: float = 8.0) -> Dict[str, Any]:
    """Look for published emails on the creator's homepage and /contact page."""
    for url in (website, urljoin(website.rstrip("/") + "/", "contact")):
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                continue
            email = pick_business_email(extract_emails(resp.text))
            if email:
                return {"email": email, "url": url}
        except requests.RequestException as e:
            LOGGER.debug("Website fetch failed for %s: %s", url, e)
    return {}


def find_email(channel_description: str, channel_about_url: str,
               videos: List[Dict[str, Any]], website: Optional[str],
               crawl_website: bool = False) -> Dict[str, str]:
    """Return email + where it was found + validation status, or NOT_FOUND."""
    candidates = []
    email = pick_business_email(extract_emails(channel_description))
    if email:
        candidates.append((email, "YouTube channel description", channel_about_url))
    for v in videos:
        email = pick_business_email(extract_emails(v.get("description") or ""))
        if email:
            candidates.append((email, "YouTube video description", v.get("url", "")))
    if not candidates and crawl_website and website:
        hit = fetch_website_emails(website)
        if hit:
            candidates.append((hit["email"], "Creator website", hit["url"]))

    for email, source, url in candidates:
        status = validate_email(email)
        if status == "valid":
            return {"email": email, "email_source": source, "email_source_url": url,
                    "email_validation_status": status}
    if candidates:  # found something but it failed validation: report, don't use
        email, source, url = candidates[0]
        return {"email": email, "email_source": source, "email_source_url": url,
                "email_validation_status": validate_email(email)}
    return dict(NOT_FOUND)
