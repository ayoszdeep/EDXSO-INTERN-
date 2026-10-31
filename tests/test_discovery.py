from src.database.db import fetch_all, get_all_influencers
from src.discovery.discover import collect_profiles, discover_influencers
from src.processing.metrics import compute_engagement, days_since, latest_upload_date


def test_discovery_deduplicates_channels_across_queries(fake_client, config):
    found = discover_influencers(fake_client, config)
    ids = [c["channel_id"] for c in found]
    assert sorted(ids) == ["UC_BIG", "UC_LOWENG", "UC_PHONE", "UC_PY"]
    assert len(get_all_influencers()) == 4


def test_discovery_respects_max_channels(fake_client, config):
    config["max_channels"] = 2
    assert len(discover_influencers(fake_client, config)) == 2


def test_collection_stores_real_metrics(fake_client, config):
    discover_influencers(fake_client, config)
    collect_profiles(fake_client, config)
    row = fetch_all("SELECT * FROM influencers WHERE influencer_id = 'UC_PY'")[0]
    assert row["follower_count"] == 42000
    assert row["engagement_rate"] == 4.5          # (400 + 50) / 10000
    assert row["profile_url"] == "https://www.youtube.com/@janecoder"
    assert row["collection_status"] == "Collected"


def test_collection_skips_video_stats_for_far_out_of_range(fake_client, config):
    discover_influencers(fake_client, config)
    collect_profiles(fake_client, config)
    assert ("UC_BIG", True) not in fake_client.calls
    row = fetch_all("SELECT engagement_rate FROM influencers WHERE influencer_id = 'UC_BIG'")[0]
    assert row["engagement_rate"] is None


def test_engagement_never_estimated_without_data():
    assert compute_engagement([])["engagement_rate"] is None
    assert compute_engagement([{"view_count": 0, "like_count": 5}])["engagement_rate"] is None
    res = compute_engagement([{"view_count": 1000, "like_count": 30, "comment_count": 10},
                              {"view_count": 2000, "like_count": 20, "comment_count": 0}])
    assert res["engagement_rate"] == 2.5 and res["videos_measured"] == 2


def test_upload_recency():
    assert latest_upload_date([{"upload_date": "20260101"}, {"upload_date": "20260301"}]) == "2026-03-01"
    assert latest_upload_date([{"upload_date": None}]) is None
    assert days_since(None) is None
