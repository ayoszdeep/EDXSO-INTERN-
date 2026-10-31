# src/outreach/dm_manager.py
"""Instagram DM handling: manual workflow only.
Instagram's Messaging API only lets a business account reply to users who
messaged it first, so cold DMs cannot be sent automatically without breaking
platform rules. Instead, DMs are queued in data/exports/instagram_dm_queue.csv;
an operator sends them by hand and then marks them sent with
`python -m src.main --mark-dm-sent <influencer_id>`.
"""
import csv
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from config.settings import settings
from src.database.db import fetch_all, get_connection

LOGGER = logging.getLogger(__name__)

READY = "Ready for Manual Send"
NO_HANDLE = "Skipped"
SENT_MANUALLY = "Sent (Manual)"


def prepare_instagram_dm(instagram_handle: str) -> Dict[str, Any]:
    """Outreach status for the DM channel, depending on whether a handle is known."""
    now = datetime.now(timezone.utc).isoformat()
    if not instagram_handle or instagram_handle == "Not Found":
        return {"status": NO_HANDLE, "sent_at": None,
                "notes": "Instagram handle Not Found in creator's public links"}
    return {"status": READY, "sent_at": None, "notes": f"Queued {now[:10]} for manual sending"}


def export_dm_queue(campaign_id: str) -> int:
    rows = fetch_all("""
        SELECT o.influencer_id, m.name, o.recipient_contact AS instagram_handle, e.instagram_url,
               m.instagram_dm, o.status
        FROM outreach o
        JOIN messages m ON m.influencer_id = o.influencer_id AND m.campaign_id = o.campaign_id
        LEFT JOIN enrichments e ON e.influencer_id = o.influencer_id
        WHERE o.campaign_id = ? AND o.channel = 'instagram_dm' AND o.status IN (?, ?)
        ORDER BY m.name
    """, (campaign_id, READY, SENT_MANUALLY))
    path = settings.DATA_ROOT / "exports" / "instagram_dm_queue.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["influencer_id", "name", "instagram_handle", "instagram_url",
                                               "instagram_dm", "status"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def mark_dm_sent(influencer_ids: List[str], campaign_id: str) -> int:
    """Record that an operator sent these DMs by hand."""
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    with get_connection() as conn:
        for iid in influencer_ids:
            cur = conn.execute(
                "UPDATE outreach SET status = ?, sent_at = ?, notes = 'Sent manually by operator' "
                "WHERE influencer_id = ? AND campaign_id = ? AND channel = 'instagram_dm' AND status = ?",
                (SENT_MANUALLY, now, iid, campaign_id, READY))
            updated += cur.rowcount
    LOGGER.info("Marked %d Instagram DM(s) as sent manually", updated)
    return updated
