# src/database/db.py
"""SQLite persistence layer.
Tables:
  influencers      - discovered channels + collected public metrics
  classifications  - niche, filter decision, brand-fit score and reasons
  enrichments      - contact details (email, Instagram, website) with sources
  messages         - one personalized email + DM per influencer per campaign
  outreach         - one row per influencer/campaign/channel (duplicate prevention)
"""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional

from config.settings import settings

LOGGER = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    influencer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    handle TEXT,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    profile_url TEXT NOT NULL,
    follower_count INTEGER,
    discovery_keyword TEXT,
    discovery_video_url TEXT,
    source TEXT,
    discovered_at TEXT,
    channel_description TEXT,
    channel_tags TEXT,
    recent_content TEXT,
    engagement_rate REAL,
    engagement_method TEXT,
    avg_views INTEGER,
    videos_measured INTEGER,
    last_upload_date TEXT,
    collection_status TEXT DEFAULT 'Pending',
    collection_error TEXT,
    collected_at TEXT
);

CREATE TABLE IF NOT EXISTS classifications (
    influencer_id TEXT PRIMARY KEY,
    niche TEXT,
    sub_niche TEXT,
    content_themes TEXT,
    content_style TEXT,
    content_language TEXT,
    content_match TEXT,
    matched_keywords TEXT,
    days_since_upload INTEGER,
    brand_fit_score INTEGER,
    score_breakdown TEXT,
    qualification_status TEXT,
    qualification_reason TEXT,
    review_required TEXT,
    classified_at TEXT,
    FOREIGN KEY (influencer_id) REFERENCES influencers(influencer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS enrichments (
    influencer_id TEXT PRIMARY KEY,
    contact_email TEXT,
    email_source TEXT,
    email_source_url TEXT,
    email_validation_status TEXT,
    instagram_handle TEXT,
    instagram_url TEXT,
    website TEXT,
    audience_age TEXT,
    audience_gender TEXT,
    audience_geography TEXT,
    enriched_at TEXT,
    FOREIGN KEY (influencer_id) REFERENCES influencers(influencer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    name TEXT,
    email_subject TEXT,
    email_body TEXT,
    email_word_count INTEGER,
    instagram_dm TEXT,
    dm_word_count INTEGER,
    personalization_signals TEXT,
    collaboration_type TEXT,
    generation_method TEXT,
    validation_status TEXT,
    validation_errors TEXT,
    review_status TEXT DEFAULT 'Pending Review',
    reviewed_at TEXT,
    generated_at TEXT,
    UNIQUE(influencer_id, campaign_id),
    FOREIGN KEY (influencer_id) REFERENCES influencers(influencer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS outreach (
    outreach_id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient_contact TEXT,
    status TEXT NOT NULL,
    sent_at TEXT,
    notes TEXT,
    UNIQUE(influencer_id, campaign_id, channel),
    FOREIGN KEY (influencer_id) REFERENCES influencers(influencer_id) ON DELETE CASCADE
);
"""


def get_db_path() -> Path:
    """Return the configured path to the SQLite database."""
    db_path = Path(settings.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a SQLite connection that commits on success."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they do not exist."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    LOGGER.info("Database ready at %s", get_db_path())


def upsert(table: str, record: Dict[str, Any], key_columns: Iterable[str]) -> None:
    """Insert a row, or update every non-key column if the key already exists."""
    keys = list(key_columns)
    columns = list(record.keys())
    updates = [c for c in columns if c not in keys]
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + c for c in columns)}) "
        f"ON CONFLICT({', '.join(keys)}) DO "
        + (f"UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in updates)}" if updates else "NOTHING")
    )
    with get_connection() as conn:
        conn.execute(sql, record)


def fetch_all(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    """Run a SELECT and return rows as dicts."""
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def fetch_one(sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def upsert_influencer(record: Dict[str, Any]) -> None:
    upsert("influencers", record, ["influencer_id"])


def upsert_classification(record: Dict[str, Any]) -> None:
    upsert("classifications", record, ["influencer_id"])


def upsert_enrichment(record: Dict[str, Any]) -> None:
    upsert("enrichments", record, ["influencer_id"])


def save_message(record: Dict[str, Any]) -> None:
    """Save (or regenerate) the single message set for an influencer in a campaign."""
    upsert("messages", record, ["influencer_id", "campaign_id"])


def record_outreach(record: Dict[str, Any]) -> None:
    """Insert or update the outreach row for one influencer/campaign/channel."""
    upsert("outreach", record, ["influencer_id", "campaign_id", "channel"])


def get_all_influencers() -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM influencers ORDER BY follower_count DESC")


def get_all_messages() -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM messages ORDER BY generated_at DESC")


def get_all_outreach_records() -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM outreach ORDER BY outreach_id")
