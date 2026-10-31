# src/processing/filtering.py
"""Stage 3: filtering & classification.
Every collected channel is checked against the campaign rules. Each failed rule
adds a reason; the final status is:
  Not Qualified - at least one hard rule failed
  Needs Review  - no rule failed but some evidence is missing/uncertain
  Qualified     - all rules passed
"""
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import load_campaign_config, settings
from src.database.db import get_all_influencers, upsert_classification
from src.processing.content_analysis import (
    classify_niche, detect_content_style, detect_language,
    evaluate_content_relevance, extract_content_themes,
)
from src.processing.metrics import days_since
from src.processing.scoring import calculate_brand_fit_score

LOGGER = logging.getLogger(__name__)


def classify_influencer(inf: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply all campaign rules to one influencer and explain the decision."""
    videos = json.loads(inf.get("recent_content") or "[]")
    titles = [v.get("title") or "" for v in videos]
    description = inf.get("channel_description") or ""
    tags = json.loads(inf.get("channel_tags") or "[]")

    niche_info = classify_niche(titles, description, tags)
    themes = extract_content_themes(titles, description)
    style = detect_content_style(titles)
    language = detect_language(titles)
    content_match, matched = evaluate_content_relevance(titles, config["target_sub_niches"])
    followers: Optional[int] = inf.get("follower_count")
    engagement: Optional[float] = inf.get("engagement_rate")
    idle_days = days_since(inf.get("last_upload_date"))

    fails: List[str] = []
    reviews: List[str] = []

    if inf.get("collection_status") != "Collected":
        reviews.append("Public profile data could not be collected")

    if followers is None:
        reviews.append("Subscriber count hidden or unavailable")
    elif followers < config["min_followers"]:
        fails.append(f"Too few followers: {followers:,} < {config['min_followers']:,}")
    elif followers > config["max_followers"]:
        fails.append(f"Too many followers: {followers:,} > {config['max_followers']:,} (not a micro-influencer)")

    if niche_info["niche"] != config["target_niche"]:
        fails.append(f"Niche is {niche_info['niche']} ({niche_info['sub_niche']}), not {config['target_niche']}")
    elif niche_info["sub_niche"] not in config["target_sub_niches"]:
        fails.append(f"Sub-niche {niche_info['sub_niche']} is outside campaign focus "
                     f"({', '.join(config['target_sub_niches'])})")

    if content_match == "Low":
        fails.append("Recent videos are not about software development or AI")
    elif content_match == "Unknown":
        reviews.append("No recent videos available to verify content relevance")

    in_range = followers is not None and config["min_followers"] <= followers <= config["max_followers"]
    if in_range:
        if engagement is None:
            reviews.append("Engagement rate could not be measured")
        elif engagement < config["min_engagement_rate"]:
            fails.append(f"Low engagement: {engagement}% < {config['min_engagement_rate']}%")

        if idle_days is None:
            reviews.append("Last upload date unknown")
        elif idle_days > config["max_days_since_last_upload"]:
            fails.append(f"Inactive: last upload {idle_days} days ago "
                         f"(limit {config['max_days_since_last_upload']})")

    if language == "Non-Latin script":
        reviews.append("Titles are mostly non-Latin script; check that an English pitch fits")

    score, breakdown = calculate_brand_fit_score(
        niche_info["sub_niche"], niche_info["niche"], content_match,
        followers, engagement, idle_days, config)

    if fails:
        status, reason = "Not Qualified", "; ".join(fails)
    elif reviews:
        status, reason = "Needs Review", "; ".join(reviews)
    else:
        status = "Qualified"
        reason = (f"Passed all rules: {followers:,} subscribers, {engagement}% engagement, "
                  f"{niche_info['sub_niche']} content ({content_match} relevance), "
                  f"last upload {idle_days} days ago")

    return {
        "influencer_id": inf["influencer_id"],
        "niche": niche_info["niche"],
        "sub_niche": niche_info["sub_niche"],
        "content_themes": "; ".join(themes),
        "content_style": style,
        "content_language": language,
        "content_match": content_match,
        "matched_keywords": ", ".join(matched),
        "days_since_upload": idle_days,
        "brand_fit_score": score,
        "score_breakdown": json.dumps(breakdown),
        "qualification_status": status,
        "qualification_reason": reason,
        "review_required": "Yes" if status == "Needs Review" else "No",
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }


def filter_influencers(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Classify every collected influencer, persist, and write the classified CSV."""
    config = config or load_campaign_config()
    influencers = get_all_influencers()
    if not influencers:
        LOGGER.warning("No influencers found in database to filter. Run discovery first.")
        return []

    results = []
    for inf in influencers:
        result = classify_influencer(inf, config)
        upsert_classification(result)
        results.append({**result, "name": inf["name"], "profile_url": inf["profile_url"],
                        "follower_count": inf.get("follower_count"),
                        "engagement_rate": inf.get("engagement_rate")})

    results.sort(key=lambda r: ({"Qualified": 0, "Needs Review": 1}.get(r["qualification_status"], 2),
                                -r["brand_fit_score"]))
    path = settings.DATA_ROOT / "processed" / "classified_influencers.csv"
    headers = ["influencer_id", "name", "profile_url", "follower_count", "engagement_rate", "niche",
               "sub_niche", "content_themes", "content_style", "content_match", "matched_keywords",
               "days_since_upload", "brand_fit_score", "score_breakdown", "qualification_status",
               "qualification_reason", "review_required"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow({**r, "engagement_rate": r["engagement_rate"] if r["engagement_rate"] is not None
                             else "Not Found"})

    counts = {s: sum(1 for r in results if r["qualification_status"] == s)
              for s in ("Qualified", "Needs Review", "Not Qualified")}
    LOGGER.info("Filtering: %d classified -> %s. Saved to %s", len(results), counts, path)
    return results
