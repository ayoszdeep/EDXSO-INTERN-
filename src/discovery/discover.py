# src/discovery/discover.py
"""Stage 1 (discovery) and Stage 2 (data collection).

Discovery runs every campaign search query against YouTube search and keeps each
uploading channel once (deduplicated by channel ID). Collection then fetches each
channel's public profile; channels near the target follower range also get
per-video stats (views, likes, comments, upload date) for their recent uploads.
"""
import csv
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import load_campaign_config, settings
from src.database.db import fetch_all, upsert_influencer
from src.discovery.youtube_client import YouTubeClient
from src.processing.metrics import compute_engagement, latest_upload_date

LOGGER = logging.getLogger(__name__)
SOURCE = "YouTube public pages via yt-dlp"

# Only channels inside this multiple of the follower range get per-video stats;
# far-out-of-range channels are rejected on size alone, so we skip the extra requests.
STATS_WINDOW = (0.5, 1.5)


def build_client(config: Dict[str, Any]) -> YouTubeClient:
    return YouTubeClient(
        cache_dir=settings.CACHE_DIR,
        cache_ttl_days=config.get("cache_ttl_days", 7),
        min_interval=config.get("request_interval_seconds", 0.5),
    )


def discover_influencers(client: Optional[YouTubeClient] = None,
                         config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Stage 1: search every query and record unique candidate channels."""
    config = config or load_campaign_config()
    client = client or build_client(config)
    max_channels = config.get("max_channels", 120)
    per_query = config.get("results_per_query", 20)
    modes = config.get("search_modes", ["relevance"])

    # Collect results per query first, then take channels round-robin so every
    # query contributes even when max_channels is hit early.
    per_query_channels: List[List[Dict[str, Any]]] = []
    failed_queries = 0
    for query in config.get("search_queries", []):
        found: List[Dict[str, Any]] = []
        for mode in modes:
            try:
                results = client.search(query, per_query, recent_only=(mode == "this_month"))
            except Exception as e:  # network/extraction failure: keep going with other queries
                failed_queries += 1
                LOGGER.warning("Search failed for '%s' (%s): %s", query, mode, e)
                continue
            for r in results:
                found.append({**r, "query": query})
        per_query_channels.append(found)
        LOGGER.info("Search '%s': %d results", query, len(found))

    candidates: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    depth = max((len(f) for f in per_query_channels), default=0)
    for i in range(depth):
        for found in per_query_channels:
            if i >= len(found) or len(candidates) >= max_channels:
                continue
            r = found[i]
            if r["channel_id"] in candidates:
                duplicates += 1
                continue
            candidates[r["channel_id"]] = r

    now = datetime.now(timezone.utc).isoformat()
    for cid, r in candidates.items():
        upsert_influencer({
            "influencer_id": cid,
            "name": r.get("channel") or cid,
            "platform": "YouTube",
            "profile_url": f"https://www.youtube.com/channel/{cid}",
            "discovery_keyword": r["query"],
            "discovery_video_url": r.get("video_url"),
            "source": SOURCE,
            "discovered_at": now,
        })

    LOGGER.info("Discovery: %d unique channels (%d duplicate hits removed, %d failed searches)",
                len(candidates), duplicates, failed_queries)
    if len(candidates) < 50:
        LOGGER.warning("Fewer than 50 channels discovered; add search_queries in config/campaign.json")
    return list(candidates.values())


def _collect_one(client: YouTubeClient, cid: str, config: Dict[str, Any]) -> Dict[str, Any]:
    n_videos = config.get("recent_videos_per_channel", 3)
    lo = config["min_followers"] * STATS_WINDOW[0]
    hi = config["max_followers"] * STATS_WINDOW[1]

    profile = client.channel_profile(cid, n_videos, with_video_stats=False)
    followers = profile.get("follower_count")
    if followers is not None and lo <= followers <= hi:
        profile = client.channel_profile(cid, n_videos, with_video_stats=True)
    return profile


def collect_profiles(client: Optional[YouTubeClient] = None,
                     config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Stage 2: fetch public profile + recent video stats for every discovered channel."""
    config = config or load_campaign_config()
    client = client or build_client(config)
    influencers = fetch_all("SELECT influencer_id, name FROM influencers")
    if not influencers:
        LOGGER.warning("No discovered channels in the database. Run --discover first.")
        return []

    collected: List[Dict[str, Any]] = []
    workers = max(1, config.get("collection_workers", 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_collect_one, client, inf["influencer_id"], config): inf
                   for inf in influencers}
        for n, future in enumerate(as_completed(futures), start=1):
            inf = futures[future]
            now = datetime.now(timezone.utc).isoformat()
            try:
                profile = future.result()
            except Exception as e:
                LOGGER.warning("Collection failed for %s: %s", inf["name"], e)
                upsert_influencer({"influencer_id": inf["influencer_id"], "name": inf["name"],
                                   "profile_url": f"https://www.youtube.com/channel/{inf['influencer_id']}",
                                   "collection_status": "Failed", "collection_error": str(e)[:300],
                                   "collected_at": now})
                continue

            videos = profile.get("videos", [])
            engagement = compute_engagement(videos) if profile.get("video_stats_collected") else \
                {"engagement_rate": None, "avg_views": None, "videos_measured": 0,
                 "engagement_method": "Not measured: follower count far outside target range"}
            handle = profile.get("handle")
            record = {
                "influencer_id": inf["influencer_id"],
                "name": profile.get("name") or inf["name"],
                "handle": handle,
                "profile_url": f"https://www.youtube.com/{handle}" if handle and handle.startswith("@")
                else f"https://www.youtube.com/channel/{inf['influencer_id']}",
                "follower_count": profile.get("follower_count"),
                "channel_description": profile.get("description", ""),
                "channel_tags": json.dumps(profile.get("tags", []), ensure_ascii=False),
                "recent_content": json.dumps(videos, ensure_ascii=False),
                "last_upload_date": latest_upload_date(videos),
                "collection_status": "Collected",
                "collection_error": None,
                "collected_at": now,
                **engagement,
            }
            upsert_influencer(record)
            collected.append(record)
            if n % 10 == 0:
                LOGGER.info("Collected %d/%d channel profiles", n, len(influencers))

    export_discovered_csv()
    LOGGER.info("Collection: %d profiles collected, %d failed",
                len(collected), len(influencers) - len(collected))
    return collected


def export_discovered_csv() -> None:
    """data/raw/discovered_influencers.csv: every discovered channel with raw metrics."""
    rows = fetch_all("SELECT * FROM influencers ORDER BY follower_count DESC")
    path = settings.DATA_ROOT / "raw" / "discovered_influencers.csv"
    headers = ["influencer_id", "name", "handle", "platform", "profile_url", "follower_count",
               "engagement_rate", "avg_views", "videos_measured", "last_upload_date",
               "discovery_keyword", "discovery_video_url", "source", "discovered_at",
               "collection_status", "recent_video_titles"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            videos = json.loads(r.get("recent_content") or "[]")
            writer.writerow({**r,
                             "engagement_rate": r["engagement_rate"] if r["engagement_rate"] is not None else "Not Found",
                             "recent_video_titles": " | ".join(v.get("title") or "" for v in videos)})
    LOGGER.info("Saved %d discovered channels to %s", len(rows), path)
