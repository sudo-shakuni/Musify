"""
Spotify Metadata Extractor.
Extracts playlist, album, and track details from Spotify URLs
using Spotify's public embed endpoints (zero API keys required)
with optional official Spotify API fallback.
"""

import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import requests


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Setup resilient network routing for restricted/ISP-filtered networks (SNI bypass for Spotify endpoints)
try:
    import spotapi.http.request

    _orig_spotapi_build_request = spotapi.http.request.TLSClient.build_request

    def _get_ip_for_host(host: str) -> Optional[str]:
        if "open.spotifycdn.com" in host:
            return "140.248.138.251"
        if "open.spotify.com" in host:
            return "151.101.67.42"
        if "spotify.com" in host or "spotifycdn" in host:
            return "35.186.224.24"
        return None

    def _patched_spotapi_build_request(self, method: str, url: Any, **kwargs):
        if isinstance(url, (bytes, memoryview)):
            url = url.decode("utf-8")
        headers = kwargs.setdefault("headers", {})
        m = re.search(r"https?://([^/]+)", str(url))
        if m:
            host = m.group(1).split(":")[0]
            ip = _get_ip_for_host(host)
            if ip:
                headers["Host"] = host
                url = str(url).replace(f"https://{host}", f"https://{ip}")
                kwargs["verify"] = False
        return _orig_spotapi_build_request(self, method, url, **kwargs)

    spotapi.http.request.TLSClient.build_request = _patched_spotapi_build_request
except Exception:
    pass

try:
    import urllib3.connection
    import urllib3.util.ssl_

    _orig_match = urllib3.connection._match_hostname

    def _patched_match(cert, asserted_hostname, *args, **kwargs):
        if asserted_hostname and "spotify" in asserted_hostname:
            return
        return _orig_match(cert, asserted_hostname, *args, **kwargs)

    urllib3.connection._match_hostname = _patched_match

    _orig_wrap = urllib3.util.ssl_.ssl_wrap_socket

    def _patched_ssl_wrap(sock, *args, **kwargs):
        server_hostname = kwargs.get("server_hostname")
        context = args[0] if len(args) > 0 else kwargs.get("ssl_context")
        if server_hostname and "spotify" in server_hostname:
            kwargs["server_hostname"] = None
            if context:
                context.check_hostname = False
        return _orig_wrap(sock, *args, **kwargs)

    urllib3.util.ssl_.ssl_wrap_socket = _patched_ssl_wrap
    urllib3.connection.ssl_wrap_socket = _patched_ssl_wrap
    urllib3.disable_warnings()
except Exception:
    pass


def parse_spotify_url(url_or_uri: str) -> Optional[Tuple[str, str]]:
    """
    Parses a Spotify URL or URI into (entity_type, entity_id).
    Supported types: 'playlist', 'album', 'track'.
    """
    url_or_uri = url_or_uri.strip()

    # Match Spotify URI: spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
    uri_match = re.search(r"spotify:(playlist|album|track):([a-zA-Z0-9]+)", url_or_uri)
    if uri_match:
        return uri_match.group(1), uri_match.group(2)

    # Match Spotify Web URL: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=...
    url_match = re.search(r"open\.spotify\.com/(intl-[a-z]+/)?(playlist|album|track)/([a-zA-Z0-9]+)", url_or_uri)
    if url_match:
        return url_match.group(2), url_match.group(3)

    return None


def format_duration(duration_ms: Optional[int]) -> str:
    """Formats milliseconds into M:SS."""
    if not duration_ms or duration_ms <= 0:
        return "--:--"
    seconds = int(duration_ms // 1000)
    minutes = seconds // 60
    rem_seconds = seconds % 60
    return f"{minutes}:{rem_seconds:02d}"


def get_best_image_url(entity: Dict[str, Any]) -> str:
    """Picks the highest resolution image URL from entity metadata."""
    # Check visualIdentity -> image
    images = entity.get("visualIdentity", {}).get("image", [])
    if isinstance(images, list) and images:
        # Sort by maxHeight or maxWidth descending
        sorted_images = sorted(
            images,
            key=lambda x: max(x.get("maxHeight", 0) or 0, x.get("maxWidth", 0) or 0),
            reverse=True,
        )
        if sorted_images and sorted_images[0].get("url"):
            return sorted_images[0]["url"]

    # Check coverArt -> sources
    cover_sources = entity.get("coverArt", {}).get("sources", [])
    if isinstance(cover_sources, list) and cover_sources:
        sorted_sources = sorted(
            cover_sources,
            key=lambda x: (x.get("height", 0) or 0) * (x.get("width", 0) or 0),
            reverse=True,
        )
        if sorted_sources and sorted_sources[0].get("url"):
            return sorted_sources[0]["url"]

    # Check direct images array
    direct_images = entity.get("images", [])
    if isinstance(direct_images, list) and direct_images:
        return direct_images[0].get("url", "")

    return ""


def fetch_from_embed(entity_type: str, entity_id: str) -> Dict[str, Any]:
    """
    Fetches structured metadata using Spotify's public embed interface.
    No credentials or tokens are needed.
    """
    embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
    last_err = None
    response = None
    for attempt in range(3):
        try:
            response = requests.get(embed_url, headers=HEADERS, timeout=25)
            response.raise_for_status()
            break
        except Exception as err:
            last_err = err
            time.sleep(1)
    if response is None:
        raise ValueError(f"Failed to fetch embed data after 3 attempts: {last_err}")

    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', response.text)
    if not match:
        raise ValueError("Could not parse Spotify metadata from embed page.")

    data = json.loads(match.group(1))
    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
    if not entity:
        raise ValueError(f"Spotify entity not found or private for {entity_type} {entity_id}.")

    title = entity.get("title") or entity.get("name") or "Unknown Title"
    subtitle = entity.get("subtitle") or ""
    author = ""
    authors_data = entity.get("authors")
    if isinstance(authors_data, list) and authors_data:
        author = ", ".join([a.get("name", "") for a in authors_data if isinstance(a, dict)])
    if not author:
        author = subtitle

    cover_url = get_best_image_url(entity)

    # Release date / year
    release_date_raw = entity.get("releaseDate", {})
    year = ""
    if isinstance(release_date_raw, dict):
        iso = release_date_raw.get("isoString", "")
        if iso and len(iso) >= 4:
            year = iso[:4]
    elif isinstance(release_date_raw, str) and len(release_date_raw) >= 4:
        year = release_date_raw[:4]

    tracks: List[Dict[str, Any]] = []

    if entity_type == "track":
        # Single track
        artists_list = entity.get("artists", [])
        if isinstance(artists_list, list) and artists_list:
            artists_str = ", ".join([a.get("name", "") for a in artists_list if isinstance(a, dict)])
        else:
            artists_str = subtitle or "Unknown Artist"

        duration_ms = entity.get("duration", 0)
        audio_preview = entity.get("audioPreview", {}).get("url") if isinstance(entity.get("audioPreview"), dict) else None

        tracks.append({
            "id": entity_id,
            "uri": entity.get("uri", f"spotify:track:{entity_id}"),
            "title": title,
            "artists": artists_str,
            "album": title,
            "duration_ms": duration_ms,
            "duration_formatted": format_duration(duration_ms),
            "preview_url": audio_preview,
            "cover_url": cover_url,
            "track_number": 1,
            "year": year,
            "is_explicit": bool(entity.get("isExplicit", False)),
            "spotify_url": f"https://open.spotify.com/track/{entity_id}",
        })

    else:
        # Playlist or Album
        raw_tracks = entity.get("trackList", [])
        album_name = title if entity_type == "album" else ""

        for idx, t in enumerate(raw_tracks, 1):
            if not isinstance(t, dict):
                continue

            track_title = t.get("title") or "Unknown Track"
            track_artist = t.get("subtitle") or author or "Unknown Artist"
            track_uri = t.get("uri") or ""
            track_id = track_uri.split(":")[-1] if track_uri else f"track_{idx}"
            duration_ms = t.get("duration", 0)

            audio_preview = None
            if isinstance(t.get("audioPreview"), dict):
                audio_preview = t["audioPreview"].get("url")

            tracks.append({
                "id": track_id,
                "uri": track_uri or f"spotify:track:{track_id}",
                "title": track_title,
                "artists": track_artist,
                "album": album_name or track_title,
                "duration_ms": duration_ms,
                "duration_formatted": format_duration(duration_ms),
                "preview_url": audio_preview,
                "cover_url": cover_url,
                "track_number": idx,
                "year": year,
                "is_explicit": bool(t.get("isExplicit", False)),
                "spotify_url": f"https://open.spotify.com/track/{track_id}" if track_id else "",
            })

    total_duration_ms = sum(t["duration_ms"] for t in tracks)

    return {
        "id": entity_id,
        "type": entity_type,
        "title": title,
        "author": author,
        "subtitle": subtitle,
        "description": entity.get("subtitle") if entity_type == "playlist" else "",
        "cover_url": cover_url,
        "year": year,
        "total_tracks": len(tracks),
        "total_duration_ms": total_duration_ms,
        "total_duration_formatted": format_duration(total_duration_ms),
        "tracks": tracks,
    }


def fetch_playlist_unlimited(playlist_id: str) -> Dict[str, Any]:
    """
    Fetches all tracks from a playlist without the 100-track cap
    using Spotify's internal GraphQL/Pathfinder pagination.
    """
    import spotapi.client
    # Pre-populate secret cache to avoid any external lookup delays
    if spotapi.client._secret_cache is None:
        spotapi.client._secret_cache = spotapi.client._FALLBACK_SECRET
        spotapi.client._cache_expiry = float("inf")

    from spotapi.playlist import PublicPlaylist

    pl = PublicPlaylist(playlist_id)
    # Fetch first batch of up to 343 tracks along with playlist metadata in ONE call
    first_res = pl.get_playlist_info(limit=343, offset=0)
    pl_data = first_res.get("data", {}).get("playlistV2", {})
    if pl_data.get("__typename") == "NotFound":
        raise ValueError(f"Playlist '{playlist_id}' not found or is private.")

    title = pl_data.get("name") or "Spotify Playlist"
    description = pl_data.get("description") or ""
    author = pl_data.get("ownerV2", {}).get("data", {}).get("name") or "Spotify"

    # Get cover image
    cover_url = ""
    images = pl_data.get("images", {})
    if isinstance(images, dict):
        items = images.get("items", [])
        if items and isinstance(items, list):
            sources = items[0].get("sources", [])
            if sources and isinstance(sources, list):
                cover_url = sources[0].get("url", "")
    elif isinstance(images, list) and images:
        cover_url = images[0].get("url", "")

    content = pl_data.get("content", {})
    total_count = content.get("totalCount", 0)
    all_raw_items = list(content.get("items", []))

    # Paginate remaining chunks if playlist has > 343 songs
    offset = 343
    while offset < total_count:
        try:
            chunk_res = pl.get_playlist_info(limit=343, offset=offset)
            chunk_items = chunk_res.get("data", {}).get("playlistV2", {}).get("content", {}).get("items", [])
            if not chunk_items:
                break
            all_raw_items.extend(chunk_items)
            offset += 343
        except Exception:
            break

    tracks = []
    track_num = 1

    for item in all_raw_items:
        track_data = item.get("itemV2", {}).get("data", {})
        if not track_data or track_data.get("__typename") != "Track":
            continue

        track_title = track_data.get("name") or "Unknown Track"
        artists_items = track_data.get("artists", {}).get("items", [])
        artists = ", ".join(
            [a.get("profile", {}).get("name", "") for a in artists_items if a.get("profile")]
        ) or "Unknown Artist"

        album_data = track_data.get("albumOfTrack") or {}
        album_name = album_data.get("name") or title
        date_obj = album_data.get("date") or {}
        year = (date_obj.get("isoString") or "")[:4] if isinstance(date_obj, dict) else ""

        # Track cover art (highest resolution available)
        track_cover = ""
        cover_sources = album_data.get("coverArt", {}).get("sources", [])
        if cover_sources and isinstance(cover_sources, list):
            best_source = max(
                cover_sources,
                key=lambda s: (s.get("width") or 0) * (s.get("height") or 0),
            )
            track_cover = best_source.get("url", "")
        if not track_cover:
            track_cover = cover_url

        duration_ms = track_data.get("trackDuration", {}).get("totalMilliseconds") or 0
        track_uri = track_data.get("uri") or ""
        track_id = track_uri.split(":")[-1] if track_uri else f"track_{track_num}"
        is_explicit = track_data.get("contentRating", {}).get("label") == "EXPLICIT"

        tracks.append({
            "id": track_id,
            "uri": track_uri or f"spotify:track:{track_id}",
            "title": track_title,
            "artists": artists,
            "album": album_name,
            "duration_ms": duration_ms,
            "duration_formatted": format_duration(duration_ms),
            "preview_url": None,
            "cover_url": track_cover,
            "track_number": track_num,
            "year": year,
            "is_explicit": is_explicit,
            "spotify_url": f"https://open.spotify.com/track/{track_id}" if track_id else "",
        })
        track_num += 1

    total_duration_ms = sum(t["duration_ms"] for t in tracks)

    return {
        "id": playlist_id,
        "type": "playlist",
        "title": title,
        "author": author,
        "subtitle": description,
        "description": description,
        "cover_url": cover_url,
        "year": "",
        "total_tracks": len(tracks),
        "total_duration_ms": total_duration_ms,
        "total_duration_formatted": format_duration(total_duration_ms),
        "tracks": tracks,
    }


def fetch_playlist_via_spotdl(url_or_id: str) -> Dict[str, Any]:
    """
    Fallback resolver using SpotDL's native playlist extractor.
    """
    from spotdl.utils.spotify import SpotifyClient
    try:
        SpotifyClient()
    except Exception:
        SpotifyClient.init("5f573c9620494bae87890c0f08a60293", "212476d9b0f3472eaa762d90b19b0ba8")

    from spotdl.types.playlist import Playlist
    url = url_or_id if url_or_id.startswith("http") else f"https://open.spotify.com/playlist/{url_or_id}"
    meta, songs = Playlist.get_metadata(url)

    tracks = []
    for idx, s in enumerate(songs, 1):
        tracks.append({
            "id": s.song_id or f"track_{idx}",
            "uri": s.url or f"spotify:track:{s.song_id}",
            "title": s.name,
            "artists": ", ".join(s.artists) if isinstance(s.artists, list) else (s.artist or "Unknown Artist"),
            "album": s.album_name or meta.get("name", ""),
            "duration_ms": int(s.duration * 1000) if s.duration else 0,
            "duration_formatted": format_duration(int(s.duration * 1000) if s.duration else 0),
            "preview_url": None,
            "cover_url": s.cover_url or meta.get("cover_url", ""),
            "track_number": idx,
            "year": str(s.year) if s.year else "",
            "is_explicit": bool(s.explicit),
            "spotify_url": s.url or "",
        })

    total_duration_ms = sum(t["duration_ms"] for t in tracks)

    return {
        "id": meta.get("url", url_or_id),
        "type": "playlist",
        "title": meta.get("name", "Spotify Playlist"),
        "author": meta.get("author_name", "Spotify"),
        "subtitle": meta.get("description", ""),
        "description": meta.get("description", ""),
        "cover_url": meta.get("cover_url", ""),
        "year": "",
        "total_tracks": len(tracks),
        "total_duration_ms": total_duration_ms,
        "total_duration_formatted": format_duration(total_duration_ms),
        "tracks": tracks,
    }


_META_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_META_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 3600  # 1 hour in seconds


def fetch_metadata(
    url_or_uri: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main metadata resolver with caching.
    1. If cached, returns immediately (<1ms).
    2. If user provided client credentials, uses spotipy.
    3. If playlist:
       - Tries fast GraphQL pagination (limit=343).
       - Tries SpotDL native playlist engine.
       - Falls back to embed parser.
    4. If track or album, uses embed parser.
    """
    parsed = parse_spotify_url(url_or_uri)
    if not parsed:
        raise ValueError("Invalid Spotify URL or URI. Please provide a playlist, album, or track URL.")

    entity_type, entity_id = parsed
    cache_key = f"{entity_type}:{entity_id}:{client_id or ''}"
    now = time.time()

    with _META_CACHE_LOCK:
        # Evict expired entries
        expired_keys = [k for k, (ts, _) in _META_CACHE.items() if now - ts >= _CACHE_TTL]
        for k in expired_keys:
            del _META_CACHE[k]
        # Check cache
        if cache_key in _META_CACHE:
            ts, cached_data = _META_CACHE[cache_key]
            if now - ts < _CACHE_TTL:
                print(f"[Cache Hit] Returning cached metadata for {entity_type} {entity_id}")
                return cached_data

    result: Optional[Dict[str, Any]] = None

    # 1. Official API keys provided by user
    if client_id and client_secret:
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))
            
            if entity_type == "playlist":
                pl = sp.playlist(entity_id)
                tracks = []
                for idx, item in enumerate(pl.get("tracks", {}).get("items", []), 1):
                    t = item.get("track")
                    if not t:
                        continue
                    artists_str = ", ".join([a["name"] for a in t.get("artists", [])])
                    album_art = t.get("album", {}).get("images", [{}])[0].get("url", "")
                    tracks.append({
                        "id": t["id"],
                        "uri": t["uri"],
                        "title": t["name"],
                        "artists": artists_str,
                        "album": t.get("album", {}).get("name", ""),
                        "duration_ms": t.get("duration_ms", 0),
                        "duration_formatted": format_duration(t.get("duration_ms", 0)),
                        "preview_url": t.get("preview_url"),
                        "cover_url": album_art or (pl.get("images", [{}])[0].get("url", "")),
                        "track_number": idx,
                        "year": (t.get("album", {}).get("release_date", "") or "")[:4],
                        "is_explicit": t.get("explicit", False),
                        "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                    })
                cover_url = pl.get("images", [{}])[0].get("url", "") if pl.get("images") else ""
                total_duration_ms = sum(t["duration_ms"] for t in tracks)
                result = {
                    "id": entity_id,
                    "type": "playlist",
                    "title": pl.get("name", "Unknown Playlist"),
                    "author": pl.get("owner", {}).get("display_name", "Spotify"),
                    "subtitle": pl.get("description", ""),
                    "description": pl.get("description", ""),
                    "cover_url": cover_url,
                    "year": "",
                    "total_tracks": len(tracks),
                    "total_duration_ms": total_duration_ms,
                    "total_duration_formatted": format_duration(total_duration_ms),
                    "tracks": tracks,
                }
        except Exception:
            pass

    # 2. For playlists: Strategy 1 (GraphQL pagination) -> Strategy 2 (SpotDL) -> Strategy 3 (Embed)
    if not result and entity_type == "playlist":
        try:
            res = fetch_playlist_unlimited(entity_id)
            if res.get("total_tracks", 0) > 0:
                result = res
        except Exception as e:
            print(f"[Info] Strategy 1 GraphQL returned: {e}. Trying Strategy 2 (SpotDL)...")

        if not result:
            try:
                res = fetch_playlist_via_spotdl(url_or_uri)
                if res.get("total_tracks", 0) > 0:
                    result = res
            except Exception as e:
                print(f"[Info] Strategy 2 SpotDL returned: {e}. Falling back to Strategy 3 (Embed)...")

    # 3. Fallback to embed parser (tracks, albums, or fallback)
    if not result:
        result = fetch_from_embed(entity_type, entity_id)

    if result:
        with _META_CACHE_LOCK:
            # Cap cache at 50 entries
            if len(_META_CACHE) >= 50:
                oldest_key = min(_META_CACHE, key=lambda k: _META_CACHE[k][0])
                del _META_CACHE[oldest_key]
            _META_CACHE[cache_key] = (now, result)

    return result
