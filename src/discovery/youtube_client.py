# src/discovery/youtube_client.py
"""YouTube data client built on yt-dlp.
Reads only public metadata (search results, channel About info, per-video stats);
no API key, login or billing account is needed. Requests are throttled and
responses are cached on disk so repeated runs do not re-fetch the same pages.
"""
import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus

import yt_dlp

LOGGER = logging.getLogger(__name__)

_BASE_OPTS: Dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noprogress": True,
}


class _YtDlpLogger:
    """Route yt-dlp's own console output into our logger at DEBUG level."""

    def debug(self, msg: str) -> None:
        LOGGER.debug(msg)

    info = warning = error = debug


class YouTubeClient:
    def __init__(self, cache_dir: Path, cache_ttl_days: int = 7,
                 min_interval: float = 0.5, retries: int = 2):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(days=cache_ttl_days)
        self.min_interval = min_interval
        self.retries = retries
        self._lock = threading.Lock()
        self._next_slot = 0.0

    # ------------------------------------------------------------------ helpers
    def _throttle(self) -> None:
        """Space out requests globally (across worker threads)."""
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self.min_interval
        if wait > 0:
            time.sleep(wait)

    def _extract(self, url: str, flat: bool, playlist_end: Optional[int] = None) -> Dict[str, Any]:
        opts = {**_BASE_OPTS, "logger": _YtDlpLogger()}
        if flat:
            opts["extract_flat"] = True
        if playlist_end:
            opts["playlistend"] = playlist_end
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False) or {}
            except yt_dlp.utils.DownloadError as e:
                last_error = e
                LOGGER.debug("yt-dlp attempt %d failed for %s: %s", attempt + 1, url, e)
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Could not fetch {url}: {last_error}")

    def _cached(self, key: str, fetch: Callable[[], Any]) -> Any:
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                fetched_at = datetime.fromisoformat(cached["fetched_at"])
                if datetime.now(timezone.utc) - fetched_at < self.cache_ttl:
                    return cached["data"]
            except (ValueError, KeyError):
                pass  # corrupt cache entry: refetch
        data = fetch()
        path.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return data

    # --------------------------------------------------------------- public API
    def search(self, query: str, limit: int = 20, recent_only: bool = False) -> List[Dict[str, Any]]:
        """Search YouTube videos; each result carries the uploading channel.
        recent_only restricts to videos uploaded this month, which surfaces smaller,
        currently active creators instead of the biggest all-time channels.
        """
        if recent_only:
            url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgIIBA%3D%3D"
        else:
            url = f"ytsearch{limit}:{query}"
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40]
        key = f"search_{'month' if recent_only else 'rel'}_{limit}_{slug}_{hashlib.md5(query.encode()).hexdigest()[:6]}"

        def fetch() -> List[Dict[str, Any]]:
            info = self._extract(url, flat=True, playlist_end=limit)
            return [
                {
                    "video_id": e.get("id"),
                    "video_url": f"https://www.youtube.com/watch?v={e.get('id')}",
                    "title": e.get("title"),
                    "channel": e.get("channel") or e.get("uploader"),
                    "channel_id": e.get("channel_id"),
                    "view_count": e.get("view_count"),
                }
                for e in info.get("entries") or []
                if e and e.get("channel_id")
            ]

        return self._cached(key, fetch)

    def channel_profile(self, channel_id: str, n_videos: int = 3,
                        with_video_stats: bool = True) -> Dict[str, Any]:
        """Channel About data plus the N most recent long-form uploads.
        With with_video_stats=True each video also gets likes, comments, upload date
        and description (one extra request per video).
        """
        key = f"channel_{channel_id}_{n_videos}_{'full' if with_video_stats else 'flat'}"

        def fetch() -> Dict[str, Any]:
            info = self._extract(f"https://www.youtube.com/channel/{channel_id}/videos",
                                 flat=True, playlist_end=n_videos)
            videos = []
            for entry in (info.get("entries") or [])[:n_videos]:
                if not entry or not entry.get("id"):
                    continue
                video = {
                    "video_id": entry["id"],
                    "title": entry.get("title"),
                    "url": f"https://www.youtube.com/watch?v={entry['id']}",
                    "view_count": entry.get("view_count"),
                    "like_count": None,
                    "comment_count": None,
                    "upload_date": None,
                    "description": "",
                }
                if with_video_stats:
                    try:
                        full = self._extract(video["url"], flat=False)
                        video.update({
                            "view_count": full.get("view_count", video["view_count"]),
                            "like_count": full.get("like_count"),
                            "comment_count": full.get("comment_count"),
                            "upload_date": full.get("upload_date"),
                            "description": (full.get("description") or "")[:3000],
                        })
                    except RuntimeError as e:
                        LOGGER.warning("Video stats unavailable for %s: %s", video["url"], e)
                videos.append(video)

            return {
                "channel_id": channel_id,
                "name": info.get("channel") or info.get("uploader") or info.get("title"),
                "handle": info.get("uploader_id"),
                "follower_count": info.get("channel_follower_count"),
                "description": info.get("description") or "",
                "tags": info.get("tags") or [],
                "videos": videos,
                "video_stats_collected": with_video_stats,
            }

        return self._cached(key, fetch)
