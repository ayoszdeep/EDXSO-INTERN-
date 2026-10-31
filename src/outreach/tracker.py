# src/outreach/tracker.py
"""Stage 7 (review) and Stage 8 (sending + tracking).

Review: if data/exports/review_decisions.csv exists (columns influencer_id, decision
= approve|reject) those decisions are applied; otherwise, with
auto_approve_valid_messages=true, every Valid message is approved and Invalid ones
rejected. Pending messages are listed in data/exports/review_queue.csv.

Sending: only Approved messages are processed. Duplicate outreach is prevented by
  - the UNIQUE(influencer_id, campaign_id, channel) row in the outreach table
    (anything already Simulated/Sent is never re-sent), and
  - never emailing the same address twice in a campaign (shared inboxes).
"""
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.settings import load_campaign_config, settings
from src.database.db import fetch_all, get_connection, record_outreach
from src.outreach.dm_manager import READY, SENT_MANUALLY, export_dm_queue, prepare_instagram_dm
from src.outreach.email_sender import send_email

LOGGER = logging.getLogger(__name__)
DELIVERED = ("Simulated", "Sent")
STATS_PATH_NAME = "last_outreach_run.json"


def review_messages(config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    config = config or load_campaign_config()
    campaign_id = config["campaign_id"]
    decisions_path = settings.DATA_ROOT / "exports" / "review_decisions.csv"
    now = datetime.now(timezone.utc).isoformat()

    decisions: Dict[str, str] = {}
    if decisions_path.exists():
        with open(decisions_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = (row.get("decision") or "").strip().lower()
                if d in ("approve", "reject"):
                    decisions[row["influencer_id"].strip()] = "Approved" if d == "approve" else "Rejected"
        LOGGER.info("Applying %d manual review decisions from %s", len(decisions), decisions_path)

    messages = fetch_all("SELECT message_id, influencer_id, validation_status, review_status FROM messages "
                         "WHERE campaign_id = ?", (campaign_id,))
    with get_connection() as conn:
        for m in messages:
            if m["influencer_id"] in decisions:
                status = decisions[m["influencer_id"]]
            elif m["validation_status"] != "Valid":
                status = "Rejected"
            elif m["review_status"] in ("Approved", "Rejected"):
                continue  # keep earlier decision
            elif config.get("auto_approve_valid_messages", True):
                status = "Approved"
            else:
                continue
            conn.execute("UPDATE messages SET review_status = ?, reviewed_at = ? WHERE message_id = ?",
                         (status, now, m["message_id"]))

    pending = fetch_all("SELECT influencer_id, name, email_subject, email_body, instagram_dm FROM messages "
                        "WHERE campaign_id = ? AND review_status = 'Pending Review'", (campaign_id,))
    with open(settings.DATA_ROOT / "exports" / "review_queue.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["influencer_id", "name", "email_subject", "email_body",
                                               "instagram_dm", "decision"])
        writer.writeheader()
        for p in pending:
            writer.writerow({**p, "decision": ""})

    counts = {s: fetch_all("SELECT COUNT(*) AS n FROM messages WHERE campaign_id = ? AND review_status = ?",
                           (campaign_id, s))[0]["n"] for s in ("Approved", "Rejected", "Pending Review")}
    LOGGER.info("Review: %s", counts)
    return counts


def process_outreach(config: Optional[Dict[str, Any]] = None, mode: Optional[str] = None) -> Dict[str, int]:
    config = config or load_campaign_config()
    campaign_id = config["campaign_id"]
    sending_mode = mode or settings.SENDING_MODE or config.get("sending_mode", "simulation")
    brand = config["brand"]
    signature = f"{brand.get('sender_name', '')}\n{brand.get('sender_title', '')}".strip()

    messages = fetch_all("""
        SELECT m.*, e.contact_email, e.email_validation_status, e.instagram_handle
        FROM messages m LEFT JOIN enrichments e USING (influencer_id)
        WHERE m.campaign_id = ? AND m.review_status = 'Approved'
        ORDER BY m.name
    """, (campaign_id,))
    existing = {(r["influencer_id"], r["channel"]): r for r in fetch_all(
        "SELECT * FROM outreach WHERE campaign_id = ?", (campaign_id,))}
    contacted_addresses = {r["recipient_contact"].lower() for (_, ch), r in existing.items()
                           if ch == "email" and r["status"] in DELIVERED and r["recipient_contact"]}

    stats = {"approved_messages": len(messages), "emails_delivered": 0, "emails_skipped": 0,
             "emails_failed": 0, "dms_queued": 0, "dms_skipped": 0, "duplicates_prevented": 0}
    blocked_demo_send = sending_mode == "real" and brand.get("is_demo_brand") and not settings.TEST_RECIPIENT_OVERRIDE

    for m in messages:
        iid = m["influencer_id"]
        email = m.get("contact_email") or "Not Found"

        # ---- email channel
        prev = existing.get((iid, "email"))
        if prev and prev["status"] in DELIVERED:
            stats["duplicates_prevented"] += 1
            LOGGER.info("Duplicate prevented: email to %s already %s", m["name"], prev["status"].lower())
        else:
            if m.get("email_validation_status") != "valid":
                outcome = {"status": "Skipped", "sent_at": None,
                           "notes": "No valid published email ('Not Found')" if email == "Not Found"
                           else f"Email failed validation ({m.get('email_validation_status')})"}
            elif email.lower() in contacted_addresses:
                outcome = {"status": "Skipped", "sent_at": None,
                           "notes": "Duplicate address: already contacted in this campaign"}
                stats["duplicates_prevented"] += 1
            elif blocked_demo_send:
                outcome = {"status": "Failed", "sent_at": None,
                           "notes": "Demo brand: real sending to creators blocked; set TEST_RECIPIENT_OVERRIDE"}
            else:
                outcome = send_email(email, m["email_subject"], m["email_body"], sending_mode, signature)
            if outcome["status"] in DELIVERED:
                contacted_addresses.add(email.lower())
                stats["emails_delivered"] += 1
            elif outcome["status"] == "Skipped":
                stats["emails_skipped"] += 1
            else:
                stats["emails_failed"] += 1
            record_outreach({"influencer_id": iid, "campaign_id": campaign_id, "channel": "email",
                             "recipient_contact": email, **outcome})

        # ---- Instagram DM channel (manual workflow)
        prev = existing.get((iid, "instagram_dm"))
        if prev and prev["status"] in (READY, SENT_MANUALLY):
            stats["duplicates_prevented"] += 1
        else:
            dm = prepare_instagram_dm(m.get("instagram_handle"))
            stats["dms_queued" if dm["status"] == READY else "dms_skipped"] += 1
            record_outreach({"influencer_id": iid, "campaign_id": campaign_id, "channel": "instagram_dm",
                             "recipient_contact": m.get("instagram_handle") or "Not Found", **dm})

    export_dm_queue(campaign_id)
    export_outreach_log(campaign_id)
    (settings.DATA_ROOT / "exports" / STATS_PATH_NAME).write_text(
        json.dumps({**stats, "mode": sending_mode, "run_at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8")
    LOGGER.info("Outreach (%s mode): %s", sending_mode, stats)
    return stats


def export_outreach_log(campaign_id: str) -> None:
    rows = fetch_all("""
        SELECT o.*, i.name, m.message_id, m.review_status
        FROM outreach o
        JOIN influencers i USING (influencer_id)
        LEFT JOIN messages m ON m.influencer_id = o.influencer_id AND m.campaign_id = o.campaign_id
        WHERE o.campaign_id = ? ORDER BY i.name, o.channel
    """, (campaign_id,))
    path = settings.DATA_ROOT / "exports" / "outreach_log.csv"
    headers = ["influencer", "influencer_id", "channel", "contact", "message_generated", "review_status",
               "sent", "date", "status", "notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "influencer": r["name"], "influencer_id": r["influencer_id"], "channel": r["channel"],
                "contact": r["recipient_contact"], "message_generated": "Yes" if r["message_id"] else "No",
                "review_status": r["review_status"] or "",
                "sent": "Yes" if r["status"] in DELIVERED + (SENT_MANUALLY,) else "No",
                "date": (r["sent_at"] or "")[:19].replace("T", " "),
                "status": r["status"], "notes": r["notes"] or "",
            })
    LOGGER.info("Saved %d outreach log rows to %s", len(rows), path)
