"""
FastAPI Server for Spotify Playlist Cloner & Downloader.
Exposes REST and SSE endpoints for metadata inspection, download orchestration,
and local system operations.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
import io
import socket
import tempfile
import zipfile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure parent path in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.downloader import download_manager, open_folder_in_explorer
from backend.lyrics import fetch_lyrics, parse_lrc_lines
from backend.spotify_auth import spotify_auth
from backend.spotify_meta import fetch_metadata
from setup_ffmpeg import ensure_ffmpeg


def get_local_lan_ip() -> str:
    """Detects the primary local LAN IP address on Windows / Mac / Linux."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


app = FastAPI(title="Musify API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PUBLIC_TUNNEL_URL: Optional[str] = None
_TUNNEL_PROCESS: Optional[subprocess.Popen] = None


def start_cloudflare_tunnel():
    global PUBLIC_TUNNEL_URL, _TUNNEL_PROCESS
    if _TUNNEL_PROCESS is not None:
        return

    cloudflared_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "cloudflared.exe")
    if not os.path.exists(cloudflared_bin):
        import shutil
        cloudflared_bin = shutil.which("cloudflared") or cloudflared_bin

    if not os.path.exists(cloudflared_bin):
        return

    def run_tunnel():
        global PUBLIC_TUNNEL_URL, _TUNNEL_PROCESS
        try:
            cmd = [cloudflared_bin, "tunnel", "--url", "http://127.0.0.1:8800"]
            _TUNNEL_PROCESS = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in _TUNNEL_PROCESS.stdout:
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m:
                    PUBLIC_TUNNEL_URL = m.group(0)
                    print(f"\n=======================================================")
                    print(f" 🌐 PUBLIC CLOUDFLARE DOMAIN LIVE: {PUBLIC_TUNNEL_URL}")
                    print(f"=======================================================\n")
                    try:
                        with open("tunnel_url.txt", "w", encoding="utf-8") as f:
                            f.write(PUBLIC_TUNNEL_URL)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Cloudflare Tunnel] Error: {e}")

    t = threading.Thread(target=run_tunnel, daemon=True)
    t.start()


# Cloudflare tunnel is optional and NOT started automatically
# Only manual invocation if explicitly requested


class PlaylistRequest(BaseModel):
    url: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class DownloadOptions(BaseModel):
    output_dir: Optional[str] = None
    audio_format: str = "mp3"
    bitrate: str = "320"
    filename_format: str = "{artist} - {title}"
    create_m3u8: bool = True
    overwrite: bool = False
    concurrency: int = 3
    embed_artwork: bool = True


class DownloadStartRequest(BaseModel):
    playlist_title: str
    tracks: List[Dict[str, Any]]
    options: DownloadOptions


class OpenFolderRequest(BaseModel):
    path: str


class SelectFolderRequest(BaseModel):
    initial_dir: Optional[str] = None


@app.get("/api/system/info")
def get_system_info():
    """Returns system status, default music directory, and FFmpeg verification."""
    ffmpeg_bin, _ = ensure_ffmpeg()
    user_music = os.path.join(os.path.expanduser("~"), "Music", "Musify Downloads")
    os.makedirs(user_music, exist_ok=True)

    return {
        "os": sys.platform,
        "default_music_dir": user_music,
        "ffmpeg_path": ffmpeg_bin,
        "ffmpeg_ready": bool(ffmpeg_bin and os.path.exists(ffmpeg_bin)),
        "public_url": PUBLIC_TUNNEL_URL,
    }


@app.post("/api/playlist/info")
def get_playlist_info(req: PlaylistRequest):
    """Fetches full playlist metadata and track list from Spotify URL."""
    print(f"\n[Spotify Cloner] Loading URL: {req.url}")
    try:
        data = fetch_metadata(req.url, req.client_id, req.client_secret)
        print(f"[Spotify Cloner] SUCCESS: Retrieved {len(data.get('tracks', []))} tracks for '{data.get('title')}'")
        return data
    except Exception as e:
        print(f"[Spotify Cloner] ERROR: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/download/start")
async def start_download(req: DownloadStartRequest):
    """Initiates downloading and metadata tagging of selected tracks."""
    if not req.tracks:
        raise HTTPException(status_code=400, detail="No tracks selected for download.")

    loop = asyncio.get_running_loop()
    download_manager.start_download_job(
        playlist_title=req.playlist_title,
        tracks=req.tracks,
        options=req.options.model_dump() if hasattr(req.options, "model_dump") else req.options.dict(),
        loop=loop,
    )
    return {"status": "started", "total": len(req.tracks)}


@app.post("/api/download/cancel")
async def cancel_download():
    """Cancels active downloads."""
    download_manager.cancel_current_job()
    return {"status": "cancelled"}


@app.get("/api/download/status")
def get_download_status():
    """Returns status snapshot of current job."""
    return download_manager.active_job or {"status": "idle"}


@app.get("/api/download/stream")
async def stream_download_events(request: Request):
    """Server-Sent Events (SSE) endpoint for live track download and tagging progress."""
    queue = asyncio.Queue()
    download_manager.subscribers.append(queue)

    async def event_generator():
        try:
            # Yield initial snapshot if job active
            if download_manager.active_job:
                yield f"data: {json.dumps({'type': 'init', 'data': download_manager.active_job})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield ": ping\n\n"
        finally:
            if queue in download_manager.subscribers:
                download_manager.subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/open-folder")
def open_folder(req: OpenFolderRequest):
    """Opens folder in Windows Explorer."""
    success = open_folder_in_explorer(req.path)
    return {"success": success}


@app.post("/api/system/select-folder")
def select_folder(req: SelectFolderRequest):
    """Opens a native Windows directory picker dialog."""
    def run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            initial = req.initial_dir if (req.initial_dir and os.path.exists(req.initial_dir)) else os.path.expanduser("~")
            folder = filedialog.askdirectory(initialdir=initial, title="Select Download Destination Folder")
            root.destroy()
            return folder if folder else None
        except Exception as e:
            print(f"[Error selecting folder via Tkinter] {e}", file=sys.stderr)
            return None

    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_dialog)
            selected = future.result(timeout=60)
        return {"selected_dir": selected, "success": bool(selected)}
    except concurrent.futures.TimeoutError:
        return {"selected_dir": None, "success": False, "message": "Folder selection dialog timed out"}
    except Exception as e:
        return {"selected_dir": None, "success": False, "message": str(e)}


@app.get("/api/audio/stream")
def stream_audio_file(path: str):
    """Streams a downloaded local audio file so it can be previewed directly in the browser."""
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter is required.")

    # Resolve absolute path and normalize
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Audio file not found.")

    # Only allow safe audio extensions
    ext = os.path.splitext(abs_path)[1].lower()
    allowed_exts = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav"}
    if ext not in allowed_exts:
        raise HTTPException(status_code=403, detail="Forbidden: Not a supported audio file.")

    # Validate file path is within user home directory or project directory
    user_home = os.path.abspath(os.path.expanduser("~"))
    proj_root = os.path.abspath(PROJECT_ROOT)
    try:
        common_home = os.path.commonpath([abs_path, user_home])
        common_proj = os.path.commonpath([abs_path, proj_root])
        if common_home != user_home and common_proj != proj_root:
            raise HTTPException(status_code=403, detail="Access denied: File outside authorized storage boundaries.")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=403, detail="Access denied: Path validation error.")

    media_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".opus": "audio/ogg",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(abs_path, media_type=media_type, filename=os.path.basename(abs_path))


# ==========================================
# Spotify Account Linking & Library Endpoints
# ==========================================

class ManualAuthRequest(BaseModel):
    access_token: Optional[str] = None
    token: Optional[str] = None


@app.get("/api/spotify/auth/status")
def get_spotify_auth_status():
    is_auth = spotify_auth.is_authenticated()
    user = spotify_auth.get_user_info() if is_auth else None
    return {"authenticated": is_auth, "user": user}


@app.get("/api/spotify/auth/login_url")
def get_spotify_login_url(client_id: Optional[str] = None, redirect_uri: Optional[str] = None):
    try:
        res = spotify_auth.create_login_url(client_id=client_id, redirect_uri=redirect_uri)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/spotify/callback")
def spotify_oauth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(f"<h3 style='color:#ff5555;'>Spotify Authentication Error: {error}</h3><p style='color:#888;'>You may close this window.</p>")
    if not code or not state:
        return HTMLResponse("<h3 style='color:#ff5555;'>Missing code or state parameter.</h3><p style='color:#888;'>You may close this window.</p>")

    try:
        user_info = spotify_auth.exchange_code(code, state)
        user_name = user_info.get("display_name", "Spotify User")
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Connected to Spotify</title>
    <style>
        body {{ background: #121212; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #181818; padding: 40px; border-radius: 12px; text-align: center; border: 1px solid #282828; max-width: 440px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }}
        h2 {{ color: #1DB954; margin-top: 0; }}
        p {{ color: #b3b3b3; line-height: 1.5; }}
        .success-badge {{ background: #1DB95420; color: #1DB954; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; display: inline-block; margin-bottom: 12px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="success-badge">CONNECTED</div>
        <h2>Welcome, {user_name}!</h2>
        <p>Your Spotify account has been successfully linked to Musify.</p>
        <p style="font-size: 13px; color: #777;">This window will close automatically...</p>
        <script>
            if (window.opener) {{
                window.opener.postMessage({{ type: 'SPOTIFY_AUTH_SUCCESS', user: {json.dumps(user_info)} }}, '*');
                setTimeout(function() {{ window.close(); }}, 1200);
            }}
        </script>
    </div>
</body>
</html>"""
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f"<h3 style='color:#ff5555;'>Authentication Failed: {e}</h3><p style='color:#888;'>Please return to Musify and try again.</p>")


@app.post("/api/spotify/auth/manual")
def set_manual_spotify_token(req: ManualAuthRequest):
    tok = req.access_token or req.token
    if not tok:
        raise HTTPException(status_code=400, detail="access_token or token is required.")
    try:
        user_info = spotify_auth.set_manual_token(tok)
        return {"success": True, "user": user_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/spotify/auth/logout")
def spotify_logout():
    spotify_auth.logout()
    return {"success": True}


@app.get("/api/spotify/me/playlists")
def get_my_spotify_playlists(limit: int = 50, offset: int = 0):
    try:
        return spotify_auth.get_user_playlists(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/spotify/me/saved-tracks")
def get_my_saved_tracks(limit: int = 50, offset: int = 0):
    try:
        return spotify_auth.get_liked_songs_metadata(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# Lyrics Endpoints (Synced LRC & Plain)
# ==========================================

@app.get("/api/lyrics/get")
def get_track_lyrics(
    title: str,
    artist: str,
    album: Optional[str] = "",
    duration: Optional[int] = 0,
):
    """Fetches synchronized and plain lyrics from LRCLIB."""
    if not title or not artist:
        raise HTTPException(status_code=400, detail="Title and artist parameters are required.")
    data = fetch_lyrics(title, artist, album or "", duration or 0)
    if not data:
        return {"found": False, "synced_lyrics": "", "plain_lyrics": "", "lines": [], "instrumental": False}
    return {"found": True, **data}


@app.get("/api/lyrics/local")
def get_local_lyrics(path: str):
    """Reads companion .lrc file or extracts embedded lyrics from an audio file."""
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found.")

    # 1. Check for companion .lrc file
    base_no_ext = os.path.splitext(path)[0]
    lrc_path = f"{base_no_ext}.lrc"
    if os.path.exists(lrc_path):
        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
                lrc_text = f.read()
            lines = parse_lrc_lines(lrc_text)
            return {
                "found": True,
                "synced_lyrics": lrc_text,
                "plain_lyrics": "\n".join(l["text"] for l in lines if l["text"]),
                "lines": lines,
                "has_synced": bool(lines),
                "source": "local_lrc",
            }
        except Exception:
            pass

    # 2. Extract embedded tags if .mp3 or .flac
    ext = os.path.splitext(path)[1].lower()
    lyrics_text = ""
    try:
        if ext == ".mp3":
            from mutagen.mp3 import MP3
            audio = MP3(path)
            for k in audio.tags.keys() if audio.tags else []:
                if k.startswith("USLT") or k.startswith("SYLT"):
                    lyrics_text = str(audio.tags[k].text)
                    break
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            lyrics_text = audio.get("LYRICS", [""])[0]
    except Exception:
        pass

    if lyrics_text:
        lines = parse_lrc_lines(lyrics_text)
        return {
            "found": True,
            "synced_lyrics": lyrics_text if lines else "",
            "plain_lyrics": lyrics_text,
            "lines": lines,
            "has_synced": bool(lines),
            "source": "embedded_tag",
        }

    return {"found": False, "synced_lyrics": "", "plain_lyrics": "", "lines": [], "has_synced": False}


# ==========================================
# Mobile Transfer & Local Wi-Fi Streamer
# ==========================================

@app.get("/api/system/network-info")
def get_network_info():
    """Returns local LAN IP, local port, and active Cloudflare tunnel for QR transfer."""
    lan_ip = get_local_lan_ip()
    port = 8800
    lan_url = f"http://{lan_ip}:{port}"
    mobile_lan_url = f"{lan_url}/mobile"
    mobile_tunnel_url = f"{PUBLIC_TUNNEL_URL}/mobile" if PUBLIC_TUNNEL_URL else None

    return {
        "lan_ip": lan_ip,
        "port": port,
        "lan_url": lan_url,
        "mobile_lan_url": mobile_lan_url,
        "public_tunnel_url": PUBLIC_TUNNEL_URL,
        "mobile_tunnel_url": mobile_tunnel_url,
    }


@app.get("/api/mobile/library")
def get_mobile_library():
    """Scans local music download folder and returns playlists & tracks for mobile browser."""
    user_music = os.path.join(os.path.expanduser("~"), "Music", "Musify Downloads")
    os.makedirs(user_music, exist_ok=True)

    playlists = []
    for entry in os.scandir(user_music):
        if entry.is_dir():
            tracks = []
            audio_exts = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav"}
            for f in os.scandir(entry.path):
                ext = os.path.splitext(f.name)[1].lower()
                if f.is_file() and ext in audio_exts:
                    tracks.append({
                        "filename": f.name,
                        "path": f.path,
                        "size_bytes": f.stat().st_size,
                        "size_mb": f"{f.stat().st_size / (1024*1024):.1f} MB",
                    })
            if tracks:
                playlists.append({
                    "name": entry.name,
                    "path": entry.path,
                    "track_count": len(tracks),
                    "tracks": tracks,
                })

    return {"base_dir": user_music, "playlists": playlists}


def _remove_temp_file(file_path: str):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass


@app.get("/api/mobile/download-zip")
def download_playlist_as_zip(path: str, background_tasks: BackgroundTasks):
    """Streams a dynamically compressed .zip of a playlist folder with zero RAM overhead."""
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter is required.")

    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        raise HTTPException(status_code=404, detail="Playlist folder not found.")

    folder_name = os.path.basename(abs_path) or "Musify_Playlist"
    tmp_fd, tmp_zip_path = tempfile.mkstemp(suffix=".zip", prefix="musify_zip_")
    os.close(tmp_fd)

    try:
        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(abs_path):
                for f in files:
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, abs_path)
                    zf.write(full_p, arcname=rel_p)
    except Exception as e:
        _remove_temp_file(tmp_zip_path)
        raise HTTPException(status_code=500, detail=f"Failed to generate zip: {e}")

    background_tasks.add_task(_remove_temp_file, tmp_zip_path)
    encoded_name = requests.utils.quote(f"{folder_name}.zip")
    return FileResponse(
        tmp_zip_path,
        media_type="application/zip",
        filename=f"{folder_name}.zip",
        headers={
            "Content-Disposition": f'attachment; filename="{folder_name}.zip"; filename*=UTF-8\'\'{encoded_name}',
        },
    )


# Serve Frontend static assets
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_ui():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/mobile")
    def serve_mobile_ui():
        mobile_path = os.path.join(FRONTEND_DIR, "mobile.html")
        if os.path.exists(mobile_path):
            return FileResponse(mobile_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    ensure_ffmpeg()
    port = 8800
    print(f"\n=======================================================")
    print(f" 🎵 Musify — Studio-Grade Music Downloader")
    print(f" Running at: http://localhost:{port}")
    print(f"=======================================================\n")
    # Open browser automatically
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
