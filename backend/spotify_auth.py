"""
Spotify Authentication and Library Manager.
Handles OAuth 2.0 (with PKCE or Client Secret), session persistence,
user profile extraction, personal playlist browsing, and 'Liked Songs' retrieval.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import requests

# Re-use our resilient SNI-bypass urllib3 setup
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

SCOPES = [
    "user-read-private",
    "user-read-email",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
]

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8800/api/spotify/callback"

# Public fallback client ID for frictionless 1-click Spotify OAuth (PKCE flow)
FALLBACK_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"


def get_auth_storage_path() -> str:
    """Returns local path to store user auth tokens."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        target_dir = os.path.join(local_app_data, "Musify")
    else:
        target_dir = os.path.expanduser("~")
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "auth_session.json")


def _generate_pkce_pair() -> Tuple[str, str]:
    """Generates (code_verifier, code_challenge) for PKCE."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


class SpotifyAuthManager:
    """Manages Spotify authentication lifecycle, profile, and user library."""

    def __init__(self):
        self._lock = threading.Lock()
        self.session_file = get_auth_storage_path()
        self.auth_data: Dict[str, Any] = self._load_session()
        self.pending_states: Dict[str, Dict[str, Any]] = {}

    def _load_session(self) -> Dict[str, Any]:
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_session(self) -> None:
        with self._lock:
            try:
                with open(self.session_file, "w", encoding="utf-8") as f:
                    json.dump(self.auth_data, f, indent=2)
            except Exception as e:
                print(f"[Auth] Error saving session: {e}")

    def is_authenticated(self) -> bool:
        with self._lock:
            return bool(self.auth_data.get("access_token"))

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.auth_data.get("user")

    def create_login_url(self, client_id: Optional[str] = None, redirect_uri: Optional[str] = None) -> Dict[str, str]:
        """Generates Spotify OAuth URL with PKCE security."""
        cid = client_id.strip() if client_id else self.auth_data.get("client_id") or FALLBACK_CLIENT_ID
        r_uri = redirect_uri or DEFAULT_REDIRECT_URI
        code_verifier, code_challenge = _generate_pkce_pair()
        state = secrets.token_hex(16)

        with self._lock:
            self.pending_states[state] = {
                "client_id": cid,
                "redirect_uri": r_uri,
                "code_verifier": code_verifier,
                "created_at": time.time(),
            }

        params = {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": r_uri,
            "state": state,
            "scope": " ".join(SCOPES),
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
        encoded_params = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
        url = f"https://accounts.spotify.com/authorize?{encoded_params}"
        return {"url": url, "state": state}

    def exchange_code(self, code: str, state: str) -> Dict[str, Any]:
        """Exchanges OAuth code for access token and fetches user profile."""
        with self._lock:
            state_data = self.pending_states.pop(state, None)

        if not state_data:
            # Fallback state data if opened in external window
            state_data = {
                "client_id": self.auth_data.get("client_id") or FALLBACK_CLIENT_ID,
                "redirect_uri": DEFAULT_REDIRECT_URI,
                "code_verifier": None,
            }

        client_id = state_data["client_id"]
        redirect_uri = state_data["redirect_uri"]
        code_verifier = state_data.get("code_verifier")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        token_url = "https://accounts.spotify.com/api/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        resp = requests.post(token_url, data=data, headers=headers, verify=False, timeout=15)
        if resp.status_code != 200:
            raise ValueError(f"Spotify token exchange failed ({resp.status_code}): {resp.text}")

        token_json = resp.json()
        access_token = token_json.get("access_token")
        refresh_token = token_json.get("refresh_token")
        expires_in = token_json.get("expires_in", 3600)

        # Fetch user profile
        user_info = self._fetch_profile(access_token)

        with self._lock:
            self.auth_data = {
                "client_id": client_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": time.time() + expires_in,
                "user": user_info,
            }
        self._save_session()
        return user_info

    def set_manual_token(self, access_token: str) -> Dict[str, Any]:
        """Directly accepts an existing Spotify access token."""
        clean_token = access_token.strip()
        if "Bearer " in clean_token:
            clean_token = clean_token.split("Bearer ")[-1].strip().strip('"').strip("'")
        user_info = self._fetch_profile(clean_token)
        with self._lock:
            self.auth_data = {
                "client_id": None,
                "access_token": clean_token,
                "refresh_token": None,
                "expires_at": time.time() + 3600,
                "user": user_info,
            }
        self._save_session()
        return user_info

    def get_valid_token(self) -> Optional[str]:
        """Returns valid access token, auto-refreshing if expired."""
        with self._lock:
            access_token = self.auth_data.get("access_token")
            refresh_token = self.auth_data.get("refresh_token")
            expires_at = self.auth_data.get("expires_at", 0)
            client_id = self.auth_data.get("client_id") or FALLBACK_CLIENT_ID

        if not access_token:
            return None

        # If expired or expiring within 60 seconds, refresh
        if time.time() + 60 >= expires_at and refresh_token:
            try:
                refreshed = self._refresh_access_token(client_id, refresh_token)
                return refreshed
            except Exception as e:
                print(f"[Auth] Token refresh failed: {e}")

        return access_token

    def _refresh_access_token(self, client_id: str, refresh_token: str) -> str:
        token_url = "https://accounts.spotify.com/api/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(token_url, data=data, headers=headers, verify=False, timeout=15)
        if resp.status_code != 200:
            raise ValueError(f"Failed to refresh token: {resp.text}")

        res_json = resp.json()
        new_token = res_json["access_token"]
        expires_in = res_json.get("expires_in", 3600)
        with self._lock:
            self.auth_data["access_token"] = new_token
            if "refresh_token" in res_json:
                self.auth_data["refresh_token"] = res_json["refresh_token"]
            self.auth_data["expires_at"] = time.time() + expires_in
        self._save_session()
        return new_token

    def _fetch_profile(self, token: str) -> Dict[str, Any]:
        """Fetches public profile from Spotify API."""
        url = "https://api.spotify.com/v1/me"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, verify=False, timeout=15)
        if resp.status_code != 200:
            raise ValueError(f"Failed to fetch profile: {resp.text}")

        data = resp.json()
        avatar = ""
        images = data.get("images", [])
        if images and isinstance(images, list):
            avatar = images[0].get("url", "")

        return {
            "id": data.get("id"),
            "display_name": data.get("display_name") or data.get("id") or "Spotify User",
            "email": data.get("email", ""),
            "avatar_url": avatar,
            "product": data.get("product", "free"),
            "followers": data.get("followers", {}).get("total", 0),
            "country": data.get("country", ""),
            "spotify_url": data.get("external_urls", {}).get("spotify", ""),
        }

    def logout(self) -> None:
        with self._lock:
            self.auth_data = {}
        if os.path.exists(self.session_file):
            try:
                os.remove(self.session_file)
            except Exception:
                pass

    def get_user_playlists(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Fetches current user's personal playlists."""
        token = self.get_valid_token()
        if not token:
            raise ValueError("Spotify account is not linked. Please connect your account first.")

        url = f"https://api.spotify.com/v1/me/playlists?limit={limit}&offset={offset}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, verify=False, timeout=20)
        if resp.status_code != 200:
            raise ValueError(f"Could not fetch playlists: {resp.text}")

        data = resp.json()
        items = []
        for pl in data.get("items", []):
            if not pl:
                continue
            images = pl.get("images", [])
            cover = images[0].get("url", "") if images else ""
            owner = pl.get("owner", {}).get("display_name", "Spotify")
            p_url = pl.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{pl.get('id')}")
            items.append({
                "id": pl.get("id"),
                "name": pl.get("name") or "Untitled Playlist",
                "title": pl.get("name") or "Untitled Playlist",
                "description": pl.get("description") or "",
                "cover_url": cover,
                "owner": owner,
                "is_public": bool(pl.get("public", False)),
                "is_collaborative": bool(pl.get("collaborative", False)),
                "total_tracks": pl.get("tracks", {}).get("total", 0),
                "url": p_url,
                "spotify_url": p_url,
            })

        return {
            "total": data.get("total", len(items)),
            "limit": limit,
            "offset": offset,
            "items": items,
            "playlists": items,
        }

    def get_liked_songs_metadata(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """
        Fetches user's saved tracks (Liked Songs) and formats them
        as a standard Musify playlist object for instant preview & 1-click download.
        """
        token = self.get_valid_token()
        if not token:
            raise ValueError("Spotify account is not linked. Please connect your account first.")

        url = f"https://api.spotify.com/v1/me/tracks?limit={limit}&offset={offset}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, verify=False, timeout=20)
        if resp.status_code != 200:
            raise ValueError(f"Could not fetch Liked Songs: {resp.text}")

        data = resp.json()
        total_tracks = data.get("total", 0)

        tracks = []
        for idx, item in enumerate(data.get("items", []), start=offset + 1):
            t = item.get("track", {})
            if not t:
                continue

            track_id = t.get("id") or f"saved_{idx}"
            artists = ", ".join([a.get("name", "") for a in t.get("artists", [])])
            album_name = t.get("album", {}).get("name", "Liked Songs")
            album_images = t.get("album", {}).get("images", [])
            cover_url = album_images[0].get("url", "") if album_images else ""
            duration_ms = t.get("duration_ms", 0)
            seconds = duration_ms // 1000
            mins = seconds // 60
            rem_s = seconds % 60
            dur_fmt = f"{mins}:{rem_s:02d}"

            tracks.append({
                "id": track_id,
                "uri": t.get("uri") or f"spotify:track:{track_id}",
                "title": t.get("name") or "Unknown Track",
                "artists": artists or "Unknown Artist",
                "album": album_name,
                "duration_ms": duration_ms,
                "duration_formatted": dur_fmt,
                "preview_url": t.get("preview_url"),
                "cover_url": cover_url,
                "track_number": idx,
                "year": (t.get("album", {}).get("release_date") or "")[:4],
                "is_explicit": bool(t.get("explicit", False)),
                "spotify_url": t.get("external_urls", {}).get("spotify", ""),
            })

        total_duration_ms = sum(t["duration_ms"] for t in tracks)
        tot_secs = total_duration_ms // 1000
        tot_mins = tot_secs // 60
        tot_hours = tot_mins // 60
        if tot_hours > 0:
            tot_dur_fmt = f"{tot_hours}h {tot_mins % 60}m"
        else:
            tot_dur_fmt = f"{tot_mins}m {tot_secs % 60}s"

        user_info = self.get_user_info() or {}
        user_name = user_info.get("display_name", "You")

        return {
            "id": "liked-songs",
            "type": "playlist",
            "title": "Liked Songs",
            "author": user_name,
            "subtitle": f"Your saved tracks on Spotify • {total_tracks} songs",
            "description": f"Personal collection of Liked Songs saved by {user_name}.",
            "cover_url": tracks[0]["cover_url"] if tracks else "",
            "year": "",
            "total_tracks": total_tracks,
            "total_duration_ms": total_duration_ms,
            "total_duration_formatted": tot_dur_fmt,
            "tracks": tracks,
        }


# Global singleton
spotify_auth = SpotifyAuthManager()
