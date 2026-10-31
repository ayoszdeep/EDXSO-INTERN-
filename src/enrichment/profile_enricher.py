# src/enrichment/profile_enricher.py
"""Stage 4: profile enrichment.
Adds contact email (with source + validation), Instagram handle and website to
every influencer. Website crawling for emails is limited to the shortlist
(Qualified / Needs Review) to keep requests low.
Audience age, gender and geography live in private YouTube Analytics, so they
are recorded as 'Not Found (private analytics)' rather than estimated.
Writes data/processed/enriched_influencers.csv for the shortlist.
"""
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from config.settings import settings
from src.database.db import fetch_all, upsert_enrichment
from src.enrichment.contact_extractor import extract_instagram, extract_website
from src.enrichment.email_finder import find_email

LOGGER = logging.getLogger(__name__)
PRIVATE = "Not Found (private analytics)"
SHORTLIST = ("Qualified", "Needs Review")


def enrich_one(inf: Dict[str, Any], crawl_website: bool) -> Dict[str, Any]:
    videos = json.loads(inf.get("recent_content") or "[]")
    description = inf.get("channel_description") or ""
    about_url = inf["profile_url"].rstrip("/") + "/about"

    website = extract_website(description)
    instagram = extract_instagram([description] + [v.get("description") or "" for v in videos])
    email = find_email(description, about_url, videos, website, crawl_website=crawl_website)

    return {
        "influencer_id": inf["influencer_id"],
        "contact_email": email["email"],
        "email_source": email["email_source"],
        "email_source_url": email["email_source_url"],
        "email_validation_status": email["email_validation_status"],
        "instagram_handle": f"@{instagram}" if instagram else "Not Found",
        "instagram_url": f"https://www.instagram.com/{instagram}/" if instagram else "Not Found",
        "website": website or "Not Found",
        "audience_age": PRIVATE,
        "audience_gender": PRIVATE,
        "audience_geography": PRIVATE,
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }


def enrich_profiles() -> List[Dict[str, Any]]:
    rows = fetch_all("""
        SELECT i.*, c.qualification_status
        FROM influencers i LEFT JOIN classifications c USING (influencer_id)
        WHERE i.collection_status = 'Collected'
    """)
    if not rows:
        LOGGER.warning("No collected influencers to enrich. Run --collect first.")
        return []

    enriched = []
    for inf in rows:
        record = enrich_one(inf, crawl_website=inf.get("qualification_status") in SHORTLIST)
        upsert_enrichment(record)
        enriched.append(record)

    export_enriched_csv()
    found = sum(1 for r in enriched if r["email_validation_status"] == "valid")
    LOGGER.info("Enrichment: %d profiles, %d with a published valid email", len(enriched), found)
    return enriched


def export_enriched_csv() -> None:
    rows = fetch_all("""
        SELECT i.name, i.platform, i.profile_url, i.follower_count, i.engagement_rate,
               i.engagement_method, i.avg_views, c.niche, c.sub_niche, c.content_themes,
               c.content_style, i.recent_content, e.*, c.qualification_status, c.brand_fit_score
        FROM influencers i
        JOIN classifications c USING (influencer_id)
        JOIN enrichments e USING (influencer_id)
        WHERE c.qualification_status IN ('Qualified', 'Needs Review')
        ORDER BY c.brand_fit_score DESC
    """)
    path = settings.DATA_ROOT / "processed" / "enriched_influencers.csv"
    headers = ["influencer_id", "name", "platform", "profile_url", "follower_count", "engagement_rate",
               "engagement_method", "avg_views", "niche", "sub_niche", "content_themes", "content_style",
               "recent_videos", "contact_email", "email_source", "email_source_url",
               "email_validation_status", "instagram_handle", "instagram_url", "website", "audience_age",
               "audience_gender", "audience_geography", "qualification_status", "brand_fit_score"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            videos = json.loads(r.get("recent_content") or "[]")
            writer.writerow({
                **r,
                "engagement_rate": f"{r['engagement_rate']}%" if r["engagement_rate"] is not None else "Not Found",
                "recent_videos": " | ".join(f"{v.get('title')} ({v.get('url')})" for v in videos),
            })
    LOGGER.info("Saved %d shortlisted enriched profiles to %s", len(rows), path)
