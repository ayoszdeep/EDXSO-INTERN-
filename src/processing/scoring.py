# src/processing/scoring.py
"""Explainable 0-100 brand-fit score used to rank the shortlist.
  Niche fit            25  (target sub-niche 25, other Technology 10)
  Content relevance    25  (High 25, Moderate 15)
  Audience size        15  (inside follower range)
  Engagement rate      25  (>=6% 25, >=3% 18, >=minimum 10)
  Upload activity      10  (<=30 days 10, <=max days 5)
Missing data earns 0 points; nothing is estimated.
"""
from typing import Any, Dict, Optional, Tuple


def calculate_brand_fit_score(
    sub_niche: str,
    niche: str,
    content_match: str,
    follower_count: Optional[int],
    engagement_rate: Optional[float],
    days_since_upload: Optional[int],
    config: Dict[str, Any],
) -> Tuple[int, Dict[str, int]]:
    breakdown: Dict[str, int] = {}

    if sub_niche in config["target_sub_niches"]:
        breakdown["niche_fit"] = 25
    elif niche == config["target_niche"]:
        breakdown["niche_fit"] = 10
    else:
        breakdown["niche_fit"] = 0

    breakdown["content_relevance"] = {"High": 25, "Moderate": 15}.get(content_match, 0)

    in_range = follower_count is not None and config["min_followers"] <= follower_count <= config["max_followers"]
    breakdown["audience_size"] = 15 if in_range else 0

    if engagement_rate is None:
        breakdown["engagement"] = 0
    elif engagement_rate >= 6:
        breakdown["engagement"] = 25
    elif engagement_rate >= 3:
        breakdown["engagement"] = 18
    elif engagement_rate >= config["min_engagement_rate"]:
        breakdown["engagement"] = 10
    else:
        breakdown["engagement"] = 0

    if days_since_upload is None:
        breakdown["activity"] = 0
    elif days_since_upload <= 30:
        breakdown["activity"] = 10
    elif days_since_upload <= config["max_days_since_last_upload"]:
        breakdown["activity"] = 5
    else:
        breakdown["activity"] = 0

    return sum(breakdown.values()), breakdown
