# src/processing/metrics.py
"""Engagement and activity metrics computed from real per-video public stats."""
from datetime import date, datetime
from statistics import mean
from typing import Any, Dict, List, Optional

ENGAGEMENT_METHOD = "(likes + comments) / views, averaged over {n} most recent long-form videos"


def compute_engagement(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Average engagement rate (%) across videos that have view and like/comment data.
    Returns None values when nothing measurable is available (never estimated).
    """
    measurable = [
        v for v in videos
        if v.get("view_count") and (v.get("like_count") is not None or v.get("comment_count") is not None)
    ]
    if not measurable:
        return {"engagement_rate": None, "avg_views": None, "videos_measured": 0, "engagement_method": None}

    rates = [((v.get("like_count") or 0) + (v.get("comment_count") or 0)) / v["view_count"] * 100
             for v in measurable]
    method = ENGAGEMENT_METHOD.format(n=len(measurable))
    if any(v.get("like_count") is None for v in measurable):
        method += " (likes hidden on some videos; comments only)"
    return {
        "engagement_rate": round(mean(rates), 2),
        "avg_views": int(mean(v["view_count"] for v in measurable)),
        "videos_measured": len(measurable),
        "engagement_method": method,
    }


def latest_upload_date(videos: List[Dict[str, Any]]) -> Optional[str]:
    """Most recent upload date as YYYY-MM-DD, or None if unknown."""
    dates = [v["upload_date"] for v in videos if v.get("upload_date")]
    if not dates:
        return None
    d = max(dates)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and "-" not in d else d


def days_since(iso_date: Optional[str], today: Optional[date] = None) -> Optional[int]:
    if not iso_date:
        return None
    today = today or date.today()
    return (today - datetime.strptime(iso_date[:10], "%Y-%m-%d").date()).days
