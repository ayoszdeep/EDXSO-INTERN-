"""Shared fixtures: every test gets its own temporary database and data folder,
and a fake YouTube client so no test touches the network or the real outputs."""
from datetime import date, timedelta

import pytest

from config.settings import load_campaign_config, settings
from src.database.db import init_db


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    # No DNS lookups in tests: domains resolve unless they end in .invalid
    monkeypatch.setattr("src.enrichment.email_finder.check_domain_resolution",
                        lambda domain: not domain.endswith(".invalid"))
    settings.ensure_directories()
    init_db()
    yield


@pytest.fixture
def config():
    cfg = load_campaign_config()
    cfg["search_queries"] = ["python tutorial", "smartphone review"]
    cfg["search_modes"] = ["relevance"]
    cfg["collection_workers"] = 1
    return cfg


def recent(days: int) -> str:
    return (date.today() - timedelta(days=days)).strftime("%Y%m%d")


def video(title, views=10000, likes=400, comments=50, days_ago=5, description=""):
    return {"video_id": title[:11], "title": title, "url": f"https://www.youtube.com/watch?v={title[:11]}",
            "view_count": views, "like_count": likes, "comment_count": comments,
            "upload_date": recent(days_ago), "description": description}


CHANNELS = {
    "UC_PY": {"name": "Jane Coder", "handle": "@janecoder", "follower_count": 42000,
              "description": "Python and AI tutorials. Business: collabs@python.org",
              "tags": ["python", "programming"],
              "videos": [video("Build an AI Agent with LangChain in Python",
                               description="Follow me on instagram.com/janecoder"),
                         video("FastAPI Tutorial for Beginners"),
                         video("Python Automation Scripts You Need")]},
    "UC_BIG": {"name": "Mega Tech", "handle": "@megatech", "follower_count": 2500000,
               "description": "Huge tech channel", "tags": [],
               "videos": [video("Python Full Course", views=900000)]},
    "UC_PHONE": {"name": "Phone Guy", "handle": "@phoneguy", "follower_count": 30000,
                 "description": "Smartphone reviews", "tags": ["phones"],
                 "videos": [video("iPhone 18 Review: Worth It?"), video("Best Budget Android Smartphone"),
                            video("Samsung Galaxy Unboxing")]},
    "UC_LOWENG": {"name": "Quiet Dev", "handle": "@quietdev", "follower_count": 20000,
                  "description": "coding", "tags": [],
                  "videos": [video("Python tips", views=50000, likes=100, comments=5),
                             video("JavaScript tricks", views=50000, likes=100, comments=5)]},
}


class FakeYouTubeClient:
    def __init__(self):
        self.calls = []

    def search(self, query, limit=20, recent_only=False):
        ids = ["UC_PY", "UC_BIG", "UC_LOWENG"] if "python" in query else ["UC_PHONE", "UC_PY"]
        return [{"video_id": f"v{i}", "video_url": f"https://www.youtube.com/watch?v=v{i}", "title": "t",
                 "channel": CHANNELS[c]["name"], "channel_id": c, "view_count": 1} for i, c in enumerate(ids)]

    def channel_profile(self, channel_id, n_videos=3, with_video_stats=True):
        self.calls.append((channel_id, with_video_stats))
        c = CHANNELS[channel_id]
        return {"channel_id": channel_id, "name": c["name"], "handle": c["handle"],
                "follower_count": c["follower_count"], "description": c["description"], "tags": c["tags"],
                "videos": c["videos"][:n_videos], "video_stats_collected": with_video_stats}


@pytest.fixture
def fake_client():
    return FakeYouTubeClient()
