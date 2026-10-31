# src/dashboard.py
"""Simple read/review dashboard over the pipeline database.
Run from the project root:  streamlit run src/dashboard.py
Shows real pipeline results only; the Messages tab lets you approve or reject.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from config.settings import load_campaign_config
from src.database.db import fetch_all, get_connection, init_db

st.set_page_config(page_title="Influencer Outreach", layout="wide")
init_db()
config = load_campaign_config()
campaign_id = config["campaign_id"]

st.title("Micro-Influencer Outreach")
st.caption(f"{config['campaign_name']} · campaign `{campaign_id}` · brand: {config['brand']['name']}")

if not fetch_all("SELECT 1 FROM influencers LIMIT 1"):
    st.warning("The database is empty. Run `python -m src.main` first.")
    st.stop()

overview, explorer, messages_tab, tracker = st.tabs(["Overview", "Influencers", "Messages", "Outreach tracker"])

# ------------------------------------------------------------------ overview
with overview:
    def count(sql, params=()):
        return fetch_all(sql, params)[0]["n"]

    cols = st.columns(5)
    cols[0].metric("Discovered", count("SELECT COUNT(*) AS n FROM influencers"))
    cols[1].metric("In 5K-100K range", count(
        "SELECT COUNT(*) AS n FROM influencers WHERE follower_count BETWEEN ? AND ?",
        (config["min_followers"], config["max_followers"])))
    for col, status in zip(cols[2:], ("Qualified", "Needs Review", "Not Qualified")):
        col.metric(status, count(
            "SELECT COUNT(*) AS n FROM classifications WHERE qualification_status = ?", (status,)))

    cols = st.columns(5)
    cols[0].metric("Qualified with valid email", count(
        "SELECT COUNT(*) AS n FROM enrichments e JOIN classifications c USING (influencer_id) "
        "WHERE c.qualification_status = 'Qualified' AND e.email_validation_status = 'valid'"))
    cols[1].metric("Messages generated", count("SELECT COUNT(*) AS n FROM messages WHERE campaign_id = ?", (campaign_id,)))
    cols[2].metric("Emails simulated/sent", count(
        "SELECT COUNT(*) AS n FROM outreach WHERE channel = 'email' AND status IN ('Simulated', 'Sent')"))
    cols[3].metric("Emails skipped", count(
        "SELECT COUNT(*) AS n FROM outreach WHERE channel = 'email' AND status = 'Skipped'"))
    cols[4].metric("DMs ready to send", count(
        "SELECT COUNT(*) AS n FROM outreach WHERE channel = 'instagram_dm' AND status = 'Ready for Manual Send'"))

    st.subheader("Why creators were rejected")
    reasons = {}
    for r in fetch_all("SELECT qualification_reason FROM classifications WHERE qualification_status = 'Not Qualified'"):
        for part in r["qualification_reason"].split("; "):
            key = part.split(":")[0].split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
    st.bar_chart(pd.Series(reasons, name="channels").sort_values(ascending=False))

# ------------------------------------------------------------------ influencers
with explorer:
    rows = fetch_all("""
        SELECT i.name, i.profile_url, i.follower_count AS subscribers, i.engagement_rate AS "engagement_%",
               c.sub_niche, c.content_themes, c.brand_fit_score AS score, c.qualification_status AS status,
               c.qualification_reason AS reason, e.contact_email AS email, e.email_source_url AS email_source,
               e.instagram_handle AS instagram, e.website
        FROM influencers i LEFT JOIN classifications c USING (influencer_id)
        LEFT JOIN enrichments e USING (influencer_id)
    """)
    df = pd.DataFrame(rows)
    f1, f2, f3 = st.columns([2, 2, 3])
    status = f1.multiselect("Status", ["Qualified", "Needs Review", "Not Qualified"], default=["Qualified"])
    only_email = f2.checkbox("Only with a valid email")
    query = f3.text_input("Search name or theme")
    view = df[df["status"].isin(status)] if status else df
    if only_email:
        view = view[view["email"].fillna("Not Found") != "Not Found"]
    if query:
        mask = view["name"].str.contains(query, case=False, na=False) | \
            view["content_themes"].str.contains(query, case=False, na=False)
        view = view[mask]
    view = view.sort_values(["score", "subscribers"], ascending=False)
    st.caption(f"{len(view)} of {len(df)} channels")
    st.dataframe(view, width="stretch", hide_index=True,
                 column_config={"profile_url": st.column_config.LinkColumn("profile", display_text="open")})

# ------------------------------------------------------------------ messages
with messages_tab:
    msgs = fetch_all("""
        SELECT m.*, i.profile_url, i.follower_count, i.engagement_rate, e.contact_email, e.instagram_handle
        FROM messages m JOIN influencers i USING (influencer_id)
        LEFT JOIN enrichments e USING (influencer_id)
        WHERE m.campaign_id = ? ORDER BY m.name
    """, (campaign_id,))
    if not msgs:
        st.info("No messages yet. Run the pipeline first.")
    else:
        by_name = {m["name"]: m for m in msgs}
        m = by_name[st.selectbox("Creator", list(by_name))]
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**Subject:** {m['email_subject']}")
            st.info(m["email_body"])
            st.caption(f"{m['email_word_count']} words (limit 60-90)")
            st.markdown("**Instagram DM**")
            st.success(m["instagram_dm"])
            st.caption(f"{m['dm_word_count']} words (limit 15-30)")
        with right:
            st.markdown(f"[{m['name']}]({m['profile_url']})")
            st.write(f"Subscribers: {m['follower_count']:,}")
            st.write(f"Engagement: {m['engagement_rate']}%" if m["engagement_rate"] is not None
                     else "Engagement: Not Found")
            st.write(f"Email: {m['contact_email']}")
            st.write(f"Instagram: {m['instagram_handle']}")
            st.write(f"Collaboration: {m['collaboration_type']}")
            st.write(f"Generated by: {m['generation_method']}")
            st.write(f"Validation: {m['validation_status']}")
            st.caption(f"Signals used: {m['personalization_signals']}")
            st.write(f"**Review status: {m['review_status']}**")
            a, r = st.columns(2)
            for label, new_status, col in (("Approve", "Approved", a), ("Reject", "Rejected", r)):
                if col.button(label, key=f"{label}-{m['message_id']}",
                              disabled=(label == "Approve" and m["validation_status"] != "Valid")):
                    with get_connection() as conn:
                        conn.execute("UPDATE messages SET review_status = ?, reviewed_at = ? WHERE message_id = ?",
                                     (new_status, datetime.now(timezone.utc).isoformat(), m["message_id"]))
                    st.rerun()
        st.caption("Approved messages are picked up by `python -m src.main --outreach`.")

# ------------------------------------------------------------------ tracker
with tracker:
    log = pd.DataFrame(fetch_all("""
        SELECT i.name AS influencer, o.channel, o.recipient_contact AS contact,
               CASE WHEN m.message_id IS NULL THEN 'No' ELSE 'Yes' END AS message_generated,
               m.review_status, o.status, o.sent_at AS date, o.notes
        FROM outreach o JOIN influencers i USING (influencer_id)
        LEFT JOIN messages m ON m.influencer_id = o.influencer_id AND m.campaign_id = o.campaign_id
        WHERE o.campaign_id = ? ORDER BY i.name, o.channel
    """, (campaign_id,)))
    if log.empty:
        st.info("No outreach recorded yet. Run `python -m src.main --outreach`.")
    else:
        channel = st.radio("Channel", ["email", "instagram_dm"], horizontal=True)
        st.dataframe(log[log["channel"] == channel], width="stretch", hide_index=True)
        st.caption("Instagram DMs are sent by hand; mark them with `python -m src.main --mark-dm-sent <influencer_id>`.")
