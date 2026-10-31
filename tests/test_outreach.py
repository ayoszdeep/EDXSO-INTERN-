import csv

from config.settings import settings
from src.ai.personalization import generate_messages
from src.database.db import fetch_all
from src.discovery.discover import collect_profiles, discover_influencers
from src.enrichment.profile_enricher import enrich_profiles
from src.outreach.dm_manager import mark_dm_sent
from src.outreach.email_sender import send_email
from src.outreach.tracker import process_outreach, review_messages
from src.processing.filtering import filter_influencers
from src.reports.exporter import export_all


def run_pipeline(fake_client, config):
    discover_influencers(fake_client, config)
    collect_profiles(fake_client, config)
    filter_influencers(config)
    enrich_profiles()
    generate_messages(config)
    review_messages(config)
    return process_outreach(config, mode="simulation")


def test_simulation_and_skip():
    assert send_email("dev@example.org", "s", "b", "simulation")["status"] == "Simulated"
    assert send_email("Not Found", "s", "b", "simulation")["status"] == "Skipped"
    assert send_email("", "s", "b", "simulation")["status"] == "Skipped"


def test_real_mode_without_credentials_fails_honestly(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_USER", "")
    res = send_email("dev@example.org", "s", "b", "real")
    assert res["status"] == "Failed" and "SMTP_USER" in res["notes"]


def test_end_to_end_pipeline(fake_client, config):
    stats = run_pipeline(fake_client, config)
    assert stats["emails_delivered"] == 1                     # UC_PY is the only qualified creator
    rows = {(r["influencer_id"], r["channel"]): r for r in fetch_all("SELECT * FROM outreach")}
    assert rows[("UC_PY", "email")]["status"] == "Simulated"
    assert rows[("UC_PY", "email")]["recipient_contact"] == "collabs@python.org"
    assert rows[("UC_PY", "instagram_dm")]["status"] == "Ready for Manual Send"
    assert rows[("UC_PY", "instagram_dm")]["recipient_contact"] == "@janecoder"

    summary = export_all(config)
    assert summary["discovered_channels"] == 4 and summary["qualified"] == 1
    with open(settings.DATA_ROOT / "exports" / "influencer_dataset.csv", encoding="utf-8") as f:
        dataset = list(csv.DictReader(f))
    assert len(dataset) == 4 and {"name", "followers", "engagement_rate", "email", "status"} <= set(dataset[0])
    assert (settings.DATA_ROOT / "exports" / "sample_messages.md").exists()


def test_rerun_prevents_duplicate_outreach(fake_client, config):
    run_pipeline(fake_client, config)
    second = run_pipeline(fake_client, config)
    assert second["emails_delivered"] == 0
    assert second["duplicates_prevented"] == 2                # email + DM already handled
    assert len(fetch_all("SELECT * FROM outreach")) == 2
    assert len(fetch_all("SELECT * FROM messages")) == 1


def test_manual_review_decision_blocks_sending(fake_client, config):
    discover_influencers(fake_client, config)
    collect_profiles(fake_client, config)
    filter_influencers(config)
    enrich_profiles()
    generate_messages(config)
    with open(settings.DATA_ROOT / "exports" / "review_decisions.csv", "w", newline="", encoding="utf-8") as f:
        f.write("influencer_id,decision\nUC_PY,reject\n")
    review_messages(config)
    assert process_outreach(config, mode="simulation")["emails_delivered"] == 0


def test_mark_dm_sent(fake_client, config):
    run_pipeline(fake_client, config)
    assert mark_dm_sent(["UC_PY"], config["campaign_id"]) == 1
    row = fetch_all("SELECT status FROM outreach WHERE channel = 'instagram_dm'")[0]
    assert row["status"] == "Sent (Manual)"
