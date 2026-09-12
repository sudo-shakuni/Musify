"""
Synchronized Lyrics Engine for Musify.
Fetches line-by-line synced LRC lyrics and plain text lyrics from LRCLIB (open-source database)
with fallback fuzzy matching, saves companion .lrc files, and embeds lyrics into audio tags.
"""

import os
import re
import threading
from typing import Any, Dict, List, Optional
import requests

LRCLIB_BASE_URL = "https://lrclib.net/api"
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Musify Music Downloader/1.1.0 (https://github.com/sudo-shakuni/Musify)"
})

_LYRICS_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
_LYRICS_CACHE_LOCK = threading.Lock()


def clean_track_title(title: str) -> str:
    """Removes noise like (feat. ...), [Remastered], - Live, etc. to maximize match rate."""
    if not title:
        return ""
    cleaned = title
    # Remove featuring brackets: (feat. X), (with X), [feat X], (ft. X)
    cleaned = re.sub(r'[\(\[\{]\s*(?:feat|ft|with)\b[^\)\]\}]*[\)\]\}]', '', cleaned, flags=re.IGNORECASE)
    # Remove version tags: (Remastered 2024), [Deluxe Edition], (Official Audio), (Bonus Track)
    cleaned = re.sub(r'[\(\[\{]\s*(?:remaster|deluxe|bonus|official|anniversary|radio edit|mono|stereo)[^\)\]\}]*[\)\]\}]', '', cleaned, flags=re.IGNORECASE)
    # Remove trailing dash suffixes: " - Radio Edit", " - Remastered 2011", " - Live from..."
    cleaned = re.sub(r'\s*-\s*(?:remaster|deluxe|bonus|official|live|radio edit|mono|stereo).*$', '', cleaned, flags=re.IGNORECASE)
    # Clean up double whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or title


def clean_artist_name(artists: str) -> str:
    """Gets the primary artist name if multiple comma/slash separated."""
    if not artists:
        return ""
    primary = re.split(r'[,/&]', artists)[0].strip()
    return primary or artists


def parse_lrc_lines(lrc_text: str) -> List[Dict[str, Any]]:
    """
    Parses an LRC string ([mm:ss.xx] lyric line) into a structured array:
    [{"time": 12.34, "text": "Lyric text"}, ...]
    """
    if not lrc_text:
        return []

    lines: List[Dict[str, Any]] = []
    pattern = re.compile(r'\[(\d{1,2}):(\d{2})(?:[\.:](\d{2,3}))?\](.*)')

    for raw_line in lrc_text.splitlines():
        raw_line = raw_line.strip()
        match = pattern.match(raw_line)
        if match:
            mins = int(match.group(1))
            secs = int(match.group(2))
            millis_str = match.group(3) or "00"
            if len(millis_str) == 2:
                millis = int(millis_str) * 10
            else:
                millis = int(millis_str[:3])

            timestamp = round(mins * 60 + secs + (millis / 1000.0), 2)
            text = match.group(4).strip()
            lines.append({"time": timestamp, "text": text})

    lines.sort(key=lambda x: x["time"])
    return lines


def fetch_lyrics(
    track_title: str,
    artist_name: str,
    album_name: str = "",
    duration_seconds: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    Queries LRCLIB with exact match, fallback cleaned match, and search fallback.
    Returns dictionary with synced_lyrics, plain_lyrics, and parsed lines.
    """
    cache_key = f"{track_title.lower()}:{artist_name.lower()}"
    with _LYRICS_CACHE_LOCK:
        if cache_key in _LYRICS_CACHE:
            return _LYRICS_CACHE[cache_key]

    result: Optional[Dict[str, Any]] = None

    # Strategy 1: Exact search via /api/get
    params = {
        "track_name": track_title,
        "artist_name": artist_name,
    }
    if album_name:
        params["album_name"] = album_name
    if duration_seconds > 0:
        params["duration"] = duration_seconds

    try:
        res = _SESSION.get(f"{LRCLIB_BASE_URL}/get", params=params, timeout=7)
        if res.status_code == 200:
            result = _format_lyrics_response(res.json())
    except Exception:
        pass

    # Strategy 2: Cleaned title / primary artist via /api/get
    if not result:
        clean_title = clean_track_title(track_title)
        primary_artist = clean_artist_name(artist_name)
        if clean_title != track_title or primary_artist != artist_name:
            try:
                res = _SESSION.get(
                    f"{LRCLIB_BASE_URL}/get",
                    params={"track_name": clean_title, "artist_name": primary_artist},
                    timeout=7,
                )
                if res.status_code == 200:
                    result = _format_lyrics_response(res.json())
            except Exception:
                pass

    # Strategy 3: General query search via /api/search?q=
    if not result:
        try:
            q = f"{clean_artist_name(artist_name)} {clean_track_title(track_title)}"
            res = _SESSION.get(f"{LRCLIB_BASE_URL}/search", params={"q": q}, timeout=7)
            if res.status_code == 200:
                items = res.json()
                if isinstance(items, list) and len(items) > 0:
                    synced_item = next((i for i in items if i.get("syncedLyrics")), items[0])
                    result = _format_lyrics_response(synced_item)
        except Exception:
            pass

    with _LYRICS_CACHE_LOCK:
        if len(_LYRICS_CACHE) >= 200:
            _LYRICS_CACHE.pop(next(iter(_LYRICS_CACHE)))
        _LYRICS_CACHE[cache_key] = result

    return result


def _format_lyrics_response(data: Dict[str, Any]) -> Dict[str, Any]:
    synced = data.get("syncedLyrics") or ""
    plain = data.get("plainLyrics") or ""
    instrumental = bool(data.get("instrumental", False))
    lines = parse_lrc_lines(synced) if synced else []

    return {
        "id": data.get("id"),
        "track_name": data.get("trackName", ""),
        "artist_name": data.get("artistName", ""),
        "album_name": data.get("albumName", ""),
        "duration": data.get("duration", 0),
        "synced_lyrics": synced,
        "plain_lyrics": plain,
        "instrumental": instrumental,
        "lines": lines,
        "has_synced": bool(synced and len(lines) > 0),
    }


def save_lrc_file(output_dir: str, base_filename_without_ext: str, synced_lyrics: str) -> Optional[str]:
    """
    Saves the .lrc synchronized lyrics file alongside the downloaded audio file.
    """
    if not synced_lyrics or not synced_lyrics.strip():
        return None

    try:
        os.makedirs(output_dir, exist_ok=True)
        lrc_path = os.path.join(output_dir, f"{base_filename_without_ext}.lrc")
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(synced_lyrics.strip() + "\n")
        return lrc_path
    except Exception as e:
        print(f"[Lyrics] Error saving .lrc file: {e}")
        return None
