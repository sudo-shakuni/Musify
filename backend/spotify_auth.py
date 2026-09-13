"""
Spotify Authentication and Library Manager.
Handles OAuth 2.0 (with PKCE or Client Secret), session persistence,
user profile extraction, personal playlist browsing, and 'Liked Songs' retrieval.
"""

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from typing import Any, Dict, List, Optional, Tuple
import requests


# Standard urllib3 warning suppression
try:
    import urllib3
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

# Registered redirect URI for official SpotDL client ID on port 9900
DEFAULT_REDIRECT_URI = "http://127.0.0.1:9900/"
FALLBACK_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
FALLBACK_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"
PORT_8800_REDIRECT_URI = "http://127.0.0.1:8800/api/spotify/callback" 


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



class OAuthCallbackListener:
    """
    Runs a lightweight local HTTP daemon on 127.0.0.1:9900 to catch
    the Spotify OAuth callback from the user's default browser (Chrome/Edge).
    """

    def __init__(self, auth_manager: "SpotifyAuthManager", port: int = 9900):
        self.auth_manager = auth_manager
        self.port = port
        self.server: Optional[socketserver.TCPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self._lock = threading.Lock()

    def start(self, timeout: int = 300) -> None:
        with self._lock:
            if self.is_running:
                return

            manager = self.auth_manager
            listener_self = self

            class CallbackHandler(http.server.BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    pass  # Quiet logging

                def do_GET(self):
                    parsed = urllib.parse.urlparse(self.path)
                    params = urllib.parse.parse_qs(parsed.query)
                    code = params.get("code", [None])[0]
                    state = params.get("state", [None])[0]
                    error = params.get("error", [None])[0]

                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()

                    if error:
                        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Musify — Spotify Connection Error</title>
    <style>
        body {{ background: #121212; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #181818; padding: 40px; border-radius: 16px; text-align: center; border: 1px solid #333; max-width: 440px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        h2 {{ color: #ff5555; margin-top: 0; }}
        p {{ color: #b3b3b3; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Authentication Cancelled</h2>
        <p>{error}</p>
        <p style="color: #777; font-size: 13px;">You may close this window and return to Musify.</p>
    </div>
</body>
</html>"""
                        self.wfile.write(html.encode("utf-8"))
                    elif code:
                        try:
                            user_info = manager.exchange_code(code, state or "")
                            user_name = user_info.get("display_name", "Spotify User")
                            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Connected to Musify!</title>
    <style>
        body {{ background: #121212; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #181818; padding: 45px; border-radius: 20px; text-align: center; border: 1px solid #282828; max-width: 460px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); }}
        .icon-circle {{ width: 68px; height: 68px; background: #1DB954; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; }}
        h2 {{ color: #fff; margin: 0 0 8px; font-size: 24px; font-weight: 700; }}
        .user-highlight {{ color: #1DB954; }}
        p {{ color: #b3b3b3; line-height: 1.5; font-size: 14px; margin: 0 0 24px; }}
        .badge {{ background: #1DB95420; color: #1DB954; border: 1px solid #1DB95440; padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600; display: inline-block; margin-bottom: 16px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon-circle">
            <svg viewBox="0 0 24 24" width="38" height="38" fill="#000"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
        </div>
        <div class="badge">CONNECTED TO MUSIFY</div>
        <h2>Welcome, <span class="user-highlight">{user_name}</span>!</h2>
        <p>Your Spotify account has been linked successfully.<br>You can safely close this tab and return to the Musify app.</p>
    </div>
    <script>
        setTimeout(function() {{ window.close(); }}, 3500);
    </script>
</body>
</html>"""
                            self.wfile.write(html.encode("utf-8"))
                        except Exception as ex:
                            html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Error</title></head><body style="background:#121212;color:#fff;font-family:sans-serif;padding:40px;"><h2>Exchange Error</h2><p>{ex}</p></body></html>"""
                            self.wfile.write(html.encode("utf-8"))
                    else:
                        self.wfile.write(b"<!DOCTYPE html><html><body style='background:#121212;color:#fff;'>Invalid request.</body></html>")

                    # Gracefully stop listener thread after handling response
                    threading.Thread(target=listener_self.stop, daemon=True).start()

            class ReusableTCPServer(socketserver.TCPServer):
                allow_reuse_address = True

            try:
                self.server = ReusableTCPServer(("127.0.0.1", self.port), CallbackHandler)
                self.is_running = True

                def run_loop():
                    try:
                        self.server.serve_forever()
                    except Exception:
                        pass
                    finally:
                        self.is_running = False

                self.thread = threading.Thread(target=run_loop, daemon=True)
                self.thread.start()

                # Timeout cleanup
                def timer():
                    time.sleep(timeout)
                    self.stop()

                threading.Thread(target=timer, daemon=True).start()
                print(f"[Auth] Dedicated OAuth callback listener running on port {self.port}")
            except Exception as err:
                print(f"[Auth] Warning: Could not bind to port {self.port} (may already be running): {err}")

    def stop(self) -> None:
        with self._lock:
            if self.server and self.is_running:
                try:
                    self.server.shutdown()
                    self.server.server_close()
                except Exception:
                    pass
                self.is_running = False

class SpotifyAuthManager:
    """Manages Spotify authentication lifecycle, profile, and user library."""

    def __init__(self):
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self.session_file = get_auth_storage_path()
        self.auth_data: Dict[str, Any] = self._load_session()
        self.pending_states: Dict[str, Dict[str, Any]] = {}
        self.callback_listener = OAuthCallbackListener(self, port=9900)

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
                tmp_path = self.session_file + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.auth_data, f, indent=2)
                os.replace(tmp_path, self.session_file)
            except Exception as e:
                print(f"[Auth] Error saving session: {e}")
                # Clean up tmp file if it exists
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

    def is_authenticated(self) -> bool:
        with self._lock:
            return bool(self.auth_data.get("access_token"))

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.auth_data.get("user")

    def create_login_url(self, client_id: Optional[str] = None, redirect_uri: Optional[str] = None) -> Dict[str, str]:
        """Generates Spotify OAuth URL (uses standard OAuth for SpotDL client, PKCE for public clients)."""
        cid = client_id.strip() if client_id else self.auth_data.get("client_id") or FALLBACK_CLIENT_ID
        r_uri = redirect_uri or DEFAULT_REDIRECT_URI
        state = secrets.token_hex(16)
        is_spotdl = (cid == FALLBACK_CLIENT_ID)

        code_verifier, code_challenge = (None, None) if is_spotdl else _generate_pkce_pair()

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
        }
        if code_challenge:
            params["code_challenge_method"] = "S256"
            params["code_challenge"] = code_challenge

        encoded_params = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
        url = f"https://accounts.spotify.com/authorize?{encoded_params}"
        return {"url": url, "state": state}

    def launch_browser_auth(self, client_id: Optional[str] = None, redirect_uri: Optional[str] = None) -> Dict[str, str]:
        """
        Starts port 9900 callback listener and launches the official Spotify
        authorization URL in the user's default system browser (Chrome/Edge/Firefox).
        Enables seamless 'Continue with Google' without embedded webview blocks.
        """
        cid = client_id.strip() if client_id else self.auth_data.get("client_id") or FALLBACK_CLIENT_ID
        r_uri = redirect_uri or DEFAULT_REDIRECT_URI

        res = self.create_login_url(client_id=cid, redirect_uri=r_uri)
        auth_url = res["url"]

        if "127.0.0.1:9900" in r_uri or ":9900" in r_uri:
            self.callback_listener.start(timeout=300)

        webbrowser.open(auth_url)
        return res

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

        if client_id == FALLBACK_CLIENT_ID:
            b64_auth = base64.b64encode(f"{FALLBACK_CLIENT_ID}:{FALLBACK_CLIENT_SECRET}".encode()).decode()
            headers["Authorization"] = f"Basic {b64_auth}"
        else:
            data["client_id"] = client_id

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
            with self._refresh_lock:
                # Double-check after acquiring lock (another thread may have refreshed)
                with self._lock:
                    expires_at = self.auth_data.get("expires_at", 0)
                    access_token = self.auth_data.get("access_token")
                if time.time() + 60 >= expires_at:
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
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if client_id == FALLBACK_CLIENT_ID:
            b64_auth = base64.b64encode(f"{FALLBACK_CLIENT_ID}:{FALLBACK_CLIENT_SECRET}".encode()).decode()
            headers["Authorization"] = f"Basic {b64_auth}"
        else:
            data["client_id"] = client_id
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
        """Fetches public profile from Spotify API with resilient fallback."""
        url = "https://api.spotify.com/v1/me"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=15)
            if resp.status_code == 200:
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
                    "product": data.get("product", "premium"),
                    "followers": data.get("followers", {}).get("total", 0),
                    "country": data.get("country", ""),
                    "spotify_url": data.get("external_urls", {}).get("spotify", ""),
                }
            else:
                print(f"[Auth] Profile fetch returned {resp.status_code}: {resp.text[:150]}")
        except Exception as e:
            print(f"[Auth] Profile fetch exception: {e}")

        # Fallback profile so Web Player and restricted tokens still work seamlessly
        return {
            "id": "spotify_user",
            "display_name": "Spotify User",
            "email": "",
            "avatar_url": "",
            "product": "premium",
            "followers": 0,
            "country": "",
            "spotify_url": "",
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
        if resp.status_code == 429:
            print("[Auth] Spotify API Rate Limit (429 QUOTA_EXCEEDED) reached for shared Client ID.")
            return {
                "total": 0,
                "limit": limit,
                "offset": offset,
                "items": [],
                "playlists": [],
                "quota_exceeded": True,
                "message": "Spotify's public app reached its daily API quota limit. You can paste any playlist URL directly into the search bar at the top to view and download it immediately!"
            }
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
            "quota_exceeded": False,
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
        if resp.status_code == 429:
            return {
                "id": "liked_songs",
                "type": "playlist",
                "title": "Liked Songs",
                "author": "You",
                "total_tracks": 0,
                "tracks": [],
                "quota_exceeded": True,
                "message": "Spotify's public app reached its daily API quota limit. Please try again later or paste specific playlist/track links into the search bar!"
            }
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
