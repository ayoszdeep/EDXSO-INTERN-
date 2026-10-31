# src/reports/exporter.py
"""Stage 9: deliverables.
  data/exports/influencer_dataset.csv  - one row per discovered influencer (the main dataset)
  data/exports/sample_messages.md      - readable email + DM for every shortlisted creator
  data/exports/run_summary.json        - counts computed from the database
"""
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.settings import load_campaign_config, settings
from src.database.db import fetch_all
from src.outreach.tracker import STATS_PATH_NAME

LOGGER = logging.getLogger(__name__)


def _fmt_rate(rate: Optional[float]) -> str:
    return f"{rate}%" if rate is not None else "Not Found"


def export_dataset(campaign_id: str) -> int:
    rows = fetch_all("""
        SELECT i.*, c.niche, c.sub_niche, c.content_themes, c.content_style, c.brand_fit_score,
               c.qualification_status, c.qualification_reason,
               e.contact_email, e.email_source, e.email_source_url, e.instagram_handle, e.website,
               e.audience_age, e.audience_gender, e.audience_geography,
               (SELECT status FROM outreach o WHERE o.influencer_id = i.influencer_id
                  AND o.campaign_id = ? AND o.channel = 'email') AS email_outreach_status
        FROM influencers i
        LEFT JOIN classifications c USING (influencer_id)
        LEFT JOIN enrichments e USING (influencer_id)
        ORDER BY CASE c.qualification_status WHEN 'Qualified' THEN 0 WHEN 'Needs Review' THEN 1 ELSE 2 END,
                 c.brand_fit_score DESC
    """, (campaign_id,))
    headers = ["name", "platform", "profile_url", "followers", "engagement_rate", "avg_views_recent",
               "niche", "sub_niche", "content_themes", "content_style", "recent_videos", "email",
               "email_source", "instagram", "website", "audience_age", "audience_gender",
               "audience_geography", "brand_fit_score", "status", "status_reason", "outreach_status",
               "influencer_id", "discovered_via", "data_source", "collected_at"]
    path = settings.DATA_ROOT / "exports" / "influencer_dataset.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            videos = json.loads(r.get("recent_content") or "[]")
            writer.writerow({
                "name": r["name"], "platform": r["platform"], "profile_url": r["profile_url"],
                "followers": r["follower_count"] if r["follower_count"] is not None else "Not Found",
                "engagement_rate": _fmt_rate(r["engagement_rate"]),
                "avg_views_recent": r["avg_views"] if r["avg_views"] is not None else "Not Found",
                "niche": r["niche"] or "Not Classified", "sub_niche": r["sub_niche"] or "",
                "content_themes": r["content_themes"] or "", "content_style": r["content_style"] or "",
                "recent_videos": " | ".join(v.get("title") or "" for v in videos),
                "email": r["contact_email"] or "Not Found",
                "email_source": r["email_source_url"] if r["email_source_url"] not in (None, "Not Found") else "",
                "instagram": r["instagram_handle"] or "Not Found", "website": r["website"] or "Not Found",
                "audience_age": r["audience_age"] or "Not Found",
                "audience_gender": r["audience_gender"] or "Not Found",
                "audience_geography": r["audience_geography"] or "Not Found",
                "brand_fit_score": r["brand_fit_score"], "status": r["qualification_status"] or "Not Classified",
                "status_reason": r["qualification_reason"] or r.get("collection_error") or "",
                "outreach_status": r["email_outreach_status"] or "",
                "influencer_id": r["influencer_id"], "discovered_via": f"search: {r['discovery_keyword']}",
                "data_source": r["source"], "collected_at": (r["collected_at"] or "")[:19],
            })
    LOGGER.info("Saved %d influencers to %s", len(rows), path)
    return len(rows)


def export_sample_messages(campaign_id: str) -> None:
    rows = fetch_all("""
        SELECT m.*, i.profile_url, i.follower_count, i.engagement_rate, e.contact_email, e.instagram_handle,
               (SELECT status FROM outreach o WHERE o.influencer_id = m.influencer_id
                  AND o.campaign_id = m.campaign_id AND o.channel = 'email') AS email_status
        FROM messages m JOIN influencers i USING (influencer_id)
        LEFT JOIN enrichments e USING (influencer_id)
        WHERE m.campaign_id = ? ORDER BY m.name
    """, (campaign_id,))
    lines = [f"# Personalized Outreach Messages ({len(rows)} creators)", "",
             f"Campaign `{campaign_id}`, generated {datetime.now(timezone.utc):%Y-%m-%d}. "
             "Every message is built from the creator's real recent videos and public metrics.", ""]
    for r in rows:
        lines += [
            f"## {r['name']}",
            f"[{r['profile_url']}]({r['profile_url']}) · {r['follower_count']:,} subscribers · "
            f"{_fmt_rate(r['engagement_rate'])} engagement · email: {r['contact_email']} · "
            f"Instagram: {r['instagram_handle']}",
            "",
            f"**Collaboration:** {r['collaboration_type']}  ",
            f"**Signals used:** {r['personalization_signals']}  ",
            f"**Generated by:** {r['generation_method']} · **Validation:** {r['validation_status']} · "
            f"**Email status:** {r['email_status'] or 'not processed'}",
            "",
            f"**Email subject:** {r['email_subject']}",
            "",
            f"> {r['email_body']}",
            "",
            f"*{r['email_word_count']} words*",
            "",
            f"**Instagram DM:** {r['instagram_dm']}  ",
            f"*{r['dm_word_count']} words*",
            "",
        ]
    path = settings.DATA_ROOT / "exports" / "sample_messages.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Saved readable messages to %s", path)


def generate_run_summary(config: Dict[str, Any]) -> Dict[str, Any]:
    campaign_id = config["campaign_id"]

    def count(sql: str, params=()) -> int:
        return fetch_all(sql, params)[0]["n"]

    status_counts = {r["qualification_status"]: r["n"] for r in fetch_all(
        "SELECT qualification_status, COUNT(*) AS n FROM classifications GROUP BY qualification_status")}
    outreach_counts = {f"{r['channel']}:{r['status']}": r["n"] for r in fetch_all(
        "SELECT channel, status, COUNT(*) AS n FROM outreach WHERE campaign_id = ? GROUP BY channel, status",
        (campaign_id,))}
    stats_path = settings.DATA_ROOT / "exports" / STATS_PATH_NAME
    last_run = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

    summary = {
        "campaign_id": campaign_id,
        "campaign_name": config["campaign_name"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "discovered_channels": count("SELECT COUNT(*) AS n FROM influencers"),
        "profiles_collected": count("SELECT COUNT(*) AS n FROM influencers WHERE collection_status = 'Collected'"),
        "in_follower_range": count("SELECT COUNT(*) AS n FROM influencers WHERE follower_count BETWEEN ? AND ?",
                                   (config["min_followers"], config["max_followers"])),
        "qualified": status_counts.get("Qualified", 0),
        "needs_review": status_counts.get("Needs Review", 0),
        "not_qualified": status_counts.get("Not Qualified", 0),
        "shortlist_with_valid_email": count(
            "SELECT COUNT(*) AS n FROM enrichments e JOIN classifications c USING (influencer_id) "
            "WHERE c.qualification_status = 'Qualified' AND e.email_validation_status = 'valid'"),
        "shortlist_with_instagram": count(
            "SELECT COUNT(*) AS n FROM enrichments e JOIN classifications c USING (influencer_id) "
            "WHERE c.qualification_status = 'Qualified' AND e.instagram_handle != 'Not Found'"),
        "messages_generated": count("SELECT COUNT(*) AS n FROM messages WHERE campaign_id = ?", (campaign_id,)),
        "messages_valid": count("SELECT COUNT(*) AS n FROM messages WHERE campaign_id = ? "
                                "AND validation_status = 'Valid'", (campaign_id,)),
        "outreach_by_channel_status": outreach_counts,
        "last_outreach_run": last_run,
    }
    path = settings.DATA_ROOT / "exports" / "run_summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def export_all(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or load_campaign_config()
    export_dataset(config["campaign_id"])
    export_sample_messages(config["campaign_id"])
    return generate_run_summary(config)
