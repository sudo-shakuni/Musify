"""
Universal Metadata Resolver for My-Music.
Supports Spotify, YouTube, YouTube Music, JioSaavn, and Amazon Music.
"""

import json
import re
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import requests

from backend.spotify_meta import fetch_metadata as fetch_spotify_metadata, format_duration


def detect_platform(url: str) -> str:
    """Detects music platform from incoming URL or string."""
    url_lower = url.lower().strip()
    if "spotify.com" in url_lower or "spotify:" in url_lower:
        return "spotify"
    if "music.youtube.com" in url_lower:
        return "youtube_music"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "jiosaavn.com" in url_lower or "saavn.com" in url_lower:
        return "jiosaavn"
    if "music.amazon." in url_lower or "amazon.com/music" in url_lower:
        return "amazon"
    return "unknown"


def resolve_youtube_metadata(url: str) -> Dict[str, Any]:
    """
    Extracts metadata from YouTube or YouTube Music videos and playlists.
    """
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("Could not extract metadata from YouTube URL.")

    is_playlist = "entries" in info
    title = info.get("title") or "YouTube Music"
    author = info.get("uploader") or info.get("channel") or "YouTube"
    cover_url = info.get("thumbnail") or ""

    tracks: List[Dict[str, Any]] = []

    if is_playlist:
        entries = [e for e in info.get("entries", []) if e]
        entity_type = "playlist"
        for idx, entry in enumerate(entries, start=1):
            t_id = entry.get("id") or f"yt_{idx}"
            raw_title = entry.get("title") or "Unknown Title"
            uploader = entry.get("uploader") or entry.get("channel") or author

            # Parse "Artist - Title" if formatted that way
            track_title = raw_title
            track_artist = uploader
            if " - " in raw_title:
                parts = raw_title.split(" - ", 1)
                track_artist = parts[0].strip()
                track_title = parts[1].strip()

            dur = int(entry.get("duration") or 0) * 1000
            t_cover = entry.get("thumbnail") or cover_url
            t_url = f"https://www.youtube.com/watch?v={t_id}"

            tracks.append({
                "id": t_id,
                "uri": f"youtube:track:{t_id}",
                "title": track_title,
                "artists": track_artist,
                "album": title,
                "duration_ms": dur,
                "duration_formatted": format_duration(dur),
                "preview_url": None,
                "cover_url": t_cover,
                "track_number": idx,
                "year": str(entry.get("release_year") or ""),
                "is_explicit": False,
                "spotify_url": t_url,
                "direct_url": t_url,
                "source": "youtube",
            })
    else:
        entity_type = "track"
        v_id = info.get("id") or "yt_1"
        raw_title = info.get("title") or "Unknown Track"
        uploader = info.get("uploader") or info.get("channel") or "Unknown Artist"

        track_title = raw_title
        track_artist = uploader
        if " - " in raw_title:
            parts = raw_title.split(" - ", 1)
            track_artist = parts[0].strip()
            track_title = parts[1].strip()

        dur = int(info.get("duration") or 0) * 1000
        t_url = f"https://www.youtube.com/watch?v={v_id}"

        tracks.append({
            "id": v_id,
            "uri": f"youtube:track:{v_id}",
            "title": track_title,
            "artists": track_artist,
            "album": track_title,
            "duration_ms": dur,
            "duration_formatted": format_duration(dur),
            "preview_url": None,
            "cover_url": cover_url,
            "track_number": 1,
            "year": str(info.get("release_year") or ""),
            "is_explicit": False,
            "spotify_url": t_url,
            "direct_url": t_url,
            "source": "youtube",
        })

    total_dur = sum(t.get("duration_ms", 0) for t in tracks)
    return {
        "id": info.get("id") or "yt",
        "type": entity_type,
        "title": title,
        "author": author,
        "subtitle": f"{len(tracks)} tracks • YouTube",
        "description": info.get("description") or "",
        "cover_url": cover_url,
        "year": str(info.get("release_year") or ""),
        "total_tracks": len(tracks),
        "total_duration_ms": total_dur,
        "total_duration_formatted": format_duration(total_dur),
        "tracks": tracks,
        "source": "youtube",
        "platform_badge": "YouTube Music" if "music.youtube" in url else "YouTube",
    }



def resolve_jiosaavn_metadata(url: str) -> Dict[str, Any]:
    """
    Extracts structured metadata from JioSaavn songs, albums, and playlists.
    Uses official JioSaavn API with graceful HTML fallback.
    """
    token_match = re.search(r"/([^/?#]+)/?$", url.strip())
    token = token_match.group(1) if token_match else None

    # Determine type
    if "/album/" in url:
        entity_type = "album"
    elif "/playlist/" in url or "/featured/" in url or "/s/playlist/" in url:
        entity_type = "playlist"
    else:
        entity_type = "song"

    # 1. Try official API first
    if token:
        try:
            api_url = f"https://www.jiosaavn.com/api.php?__call=webapi.get&token={token}&type={entity_type}&_format=json"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(api_url, headers=headers, timeout=12)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json()
                raw_songs = data.get("songs") or data.get("list") or []
                if raw_songs:
                    title = data.get("title") or data.get("name") or "JioSaavn Collection"
                    author = data.get("primary_artists") or data.get("artist") or "JioSaavn"
                    cover = (data.get("image") or "").replace("150x150", "500x500")

                    tracks = []
                    for idx, s in enumerate(raw_songs, start=1):
                        s_title = s.get("song") or s.get("title") or "Unknown Track"
                        s_artist = s.get("singers") or s.get("primary_artists") or author
                        s_album = s.get("album") or title
                        s_dur = int(s.get("duration") or 210) * 1000
                        s_cover = (s.get("image") or cover).replace("150x150", "500x500")
                        s_url = s.get("perma_url") or url

                        tracks.append({
                            "id": s.get("id") or f"saavn_{idx}",
                            "uri": f"jiosaavn:track:{s.get('id') or idx}",
                            "title": s_title,
                            "artists": s_artist,
                            "album": s_album,
                            "duration_ms": s_dur,
                            "duration_formatted": format_duration(s_dur),
                            "preview_url": None,
                            "cover_url": s_cover,
                            "track_number": idx,
                            "year": str(s.get("year") or ""),
                            "is_explicit": bool(s.get("explicit", False)),
                            "spotify_url": s_url,
                            "source": "jiosaavn",
                        })

                    total_dur = sum(t.get("duration_ms", 0) for t in tracks)
                    return {
                        "id": data.get("id") or token,
                        "type": entity_type,
                        "title": title,
                        "author": author,
                        "subtitle": f"{len(tracks)} tracks • JioSaavn",
                        "description": data.get("header_desc") or "",
                        "cover_url": cover,
                        "year": str(data.get("year") or ""),
                        "total_tracks": len(tracks),
                        "total_duration_ms": total_dur,
                        "total_duration_formatted": format_duration(total_dur),
                        "tracks": tracks,
                        "source": "jiosaavn",
                        "platform_badge": "JioSaavn",
                    }

        except Exception as api_err:
            print(f"[JioSaavn API Warning] {api_err}, falling back to HTML parsing...")

    # 2. Fallback to HTML Scraping
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise ValueError(f"Could not load JioSaavn page (HTTP {resp.status_code}).")

    html = resp.text

    title = "JioSaavn Music"
    author = "JioSaavn"
    cover_url = ""
    tracks: List[Dict[str, Any]] = []

    og_title = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    og_image = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    og_desc = re.search(r'property="og:description"\s+content="([^"]+)"', html)

    if og_title:
        title = og_title.group(1).replace("&amp;", "&")
    if og_image:
        cover_url = og_image.group(1)

    if " - " in title:
        parts = title.split(" - ", 1)
        author = parts[1].split("|")[0].strip()
        title = parts[0].strip()

    song_matches = re.findall(r'<a\s+class="[^"]*song-title[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
    artist_matches = re.findall(r'<a\s+class="[^"]*artist-title[^"]*"[^>]*>([^<]+)</a>', html)

    if song_matches:
        for idx, (s_url, s_title) in enumerate(song_matches, start=1):
            s_artist = artist_matches[idx - 1] if idx - 1 < len(artist_matches) else author
            tracks.append({
                "id": f"saavn_{idx}",
                "uri": f"jiosaavn:track:{idx}",
                "title": s_title.strip(),
                "artists": s_artist.strip(),
                "album": title,
                "duration_ms": 210000,
                "duration_formatted": "3:30",
                "preview_url": None,
                "cover_url": cover_url,
                "track_number": idx,
                "year": "",
                "is_explicit": False,
                "spotify_url": s_url if s_url.startswith("http") else f"https://www.jiosaavn.com{s_url}",
                "source": "jiosaavn",
            })
    else:
        tracks.append({
            "id": "saavn_1",
            "uri": "jiosaavn:track:1",
            "title": title,
            "artists": author,
            "album": title,
            "duration_ms": 210000,
            "duration_formatted": "3:30",
            "preview_url": None,
            "cover_url": cover_url,
            "track_number": 1,
            "year": "",
            "is_explicit": False,
            "spotify_url": url,
            "source": "jiosaavn",
        })

    total_dur = sum(t.get("duration_ms", 0) for t in tracks)
    return {
        "id": "saavn",
        "type": entity_type,
        "title": title,
        "author": author,
        "subtitle": f"{len(tracks)} tracks • JioSaavn",
        "description": og_desc.group(1) if og_desc else "",
        "cover_url": cover_url,
        "year": "",
        "total_tracks": len(tracks),
        "total_duration_ms": total_dur,
        "total_duration_formatted": format_duration(total_dur),
        "tracks": tracks,
        "source": "jiosaavn",
        "platform_badge": "JioSaavn",
    }



def resolve_amazon_metadata(url: str) -> Dict[str, Any]:
    """
    Extracts metadata from Amazon Music album, playlist, or track pages.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    html = resp.text

    title = "Amazon Music Collection"
    author = "Amazon Music"
    cover_url = ""

    og_title = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    og_image = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    og_desc = re.search(r'property="og:description"\s+content="([^"]+)"', html)

    if og_title:
        title = og_title.group(1).replace("&amp;", "&")
    if og_image:
        cover_url = og_image.group(1)

    if " - " in title:
        parts = title.split(" - ", 1)
        author = parts[0].strip()
        title = parts[1].split("|")[0].strip()

    tracks: List[Dict[str, Any]] = []

    track_matches = re.findall(r'"title":\s*"([^"]+)",\s*"artist":\s*"([^"]+)"', html)
    if track_matches:
        for idx, (t_title, t_artist) in enumerate(track_matches, start=1):
            tracks.append({
                "id": f"amz_{idx}",
                "uri": f"amazon:track:{idx}",
                "title": t_title.strip(),
                "artists": t_artist.strip(),
                "album": title,
                "duration_ms": 200000,
                "duration_formatted": "3:20",
                "preview_url": None,
                "cover_url": cover_url,
                "track_number": idx,
                "year": "",
                "is_explicit": False,
                "spotify_url": url,
                "source": "amazon",
            })
    else:
        tracks.append({
            "id": "amz_1",
            "uri": "amazon:track:1",
            "title": title,
            "artists": author,
            "album": title,
            "duration_ms": 200000,
            "duration_formatted": "3:20",
            "preview_url": None,
            "cover_url": cover_url,
            "track_number": 1,
            "year": "",
            "is_explicit": False,
            "spotify_url": url,
            "source": "amazon",
        })

    total_dur = sum(t.get("duration_ms", 0) for t in tracks)
    return {
        "id": "amazon",
        "type": "playlist" if ("/playlists/" in url or "/albums/" in url) else "track",
        "title": title,
        "author": author,
        "subtitle": f"{len(tracks)} tracks • Amazon Music",
        "description": og_desc.group(1) if og_desc else "",
        "cover_url": cover_url,
        "year": "",
        "total_tracks": len(tracks),
        "total_duration_ms": total_dur,
        "total_duration_formatted": format_duration(total_dur),
        "tracks": tracks,
        "source": "amazon",
        "platform_badge": "Amazon Music",
    }



# In-memory LRU cache with TTL (10 minutes) for ultra-fast instant repeated lookups (<1ms)
_UNIVERSAL_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_UNIVERSAL_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 600


def get_cached_metadata(cache_key: str) -> Optional[Dict[str, Any]]:
    with _UNIVERSAL_CACHE_LOCK:
        if cache_key in _UNIVERSAL_CACHE:
            ts, data = _UNIVERSAL_CACHE[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
            else:
                del _UNIVERSAL_CACHE[cache_key]
    return None


def set_cached_metadata(cache_key: str, data: Dict[str, Any]) -> None:
    with _UNIVERSAL_CACHE_LOCK:
        if len(_UNIVERSAL_CACHE) >= 100:
            oldest_key = min(_UNIVERSAL_CACHE, key=lambda k: _UNIVERSAL_CACHE[k][0])
            del _UNIVERSAL_CACHE[oldest_key]
        _UNIVERSAL_CACHE[cache_key] = (time.time(), data)


def resolve_universal_metadata(
    url: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Unified entrypoint: Automatically detects the music platform
    and extracts complete metadata and tracklists with thread-safe LRU caching.
    """
    clean_url = url.strip()
    cache_key = f"{clean_url}|{client_id or ''}"
    cached = get_cached_metadata(cache_key)
    if cached:
        return cached

    platform = detect_platform(clean_url)

    if platform == "spotify":
        data = fetch_spotify_metadata(clean_url, client_id, client_secret)
        data["source"] = "spotify"
        data["platform_badge"] = "Spotify"
        set_cached_metadata(cache_key, data)
        return data

    if platform in ("youtube", "youtube_music"):
        data = resolve_youtube_metadata(clean_url)
        set_cached_metadata(cache_key, data)
        return data

    if platform == "jiosaavn":
        data = resolve_jiosaavn_metadata(clean_url)
        set_cached_metadata(cache_key, data)
        return data

    if platform == "amazon":
        data = resolve_amazon_metadata(clean_url)
        set_cached_metadata(cache_key, data)
        return data

    try:
        data = fetch_spotify_metadata(clean_url, client_id, client_secret)
        data["source"] = "spotify"
        data["platform_badge"] = "Spotify"
        set_cached_metadata(cache_key, data)
        return data
    except Exception:
        data = resolve_youtube_metadata(clean_url)
        set_cached_metadata(cache_key, data)
        return data

