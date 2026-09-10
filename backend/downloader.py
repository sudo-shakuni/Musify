"""
Audio Downloader and Metadata Tagging Engine.
Searches YouTube Music / YouTube, downloads high-quality audio streams,
converts via FFmpeg, and embeds accurate Spotify metadata and cover artwork.
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import concurrent.futures
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

import static_ffmpeg
static_ffmpeg.add_paths()

import yt_dlp
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture


def sanitize_filename(name: str) -> str:
    """Removes illegal filesystem characters on Windows and other OSes."""
    # Replace invalid Windows chars: < > : " / \ | ? *
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', name)
    cleaned = re.sub(r'[\x00-\x1f]', '', cleaned)
    return cleaned.strip(". ") or "track"


def open_folder_in_explorer(folder_path: str) -> bool:
    """Opens a folder in Windows File Explorer."""
    abs_path = os.path.abspath(folder_path)
    if not os.path.exists(abs_path):
        os.makedirs(abs_path, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(abs_path)
            return True
        else:
            subprocess.Popen(["xdg-open", abs_path])
            return True
    except Exception as e:
        print(f"[Error opening folder] {e}", file=sys.stderr)
        return False


_IMAGE_CACHE: Dict[str, bytes] = {}
_IMAGE_CACHE_LOCK = threading.Lock()
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
})


def embed_metadata(
    file_path: str,
    title: str,
    artists: str,
    album: str,
    year: str,
    track_number: int,
    total_tracks: int,
    cover_url: Optional[str] = None,
    audio_format: str = "mp3",
    embed_artwork: bool = True,
) -> None:
    """
    Embeds complete ID3 / Vorbis / MP4 metadata and high-res cover art.
    Uses in-memory cache to avoid re-downloading duplicate album covers.
    """
    img_data = None
    if cover_url and embed_artwork:
        with _IMAGE_CACHE_LOCK:
            if cover_url in _IMAGE_CACHE:
                img_data = _IMAGE_CACHE[cover_url]

        if img_data is None:
            try:
                res = _HTTP_SESSION.get(cover_url, timeout=12)
                if res.status_code == 200:
                    img_data = res.content
                    with _IMAGE_CACHE_LOCK:
                        _IMAGE_CACHE[cover_url] = img_data
            except Exception:
                pass

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".mp3":
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except Exception:
            pass

        audio.tags.add(TIT2(encoding=3, text=[title]))
        audio.tags.add(TPE1(encoding=3, text=[artists]))
        audio.tags.add(TALB(encoding=3, text=[album]))
        if year:
            audio.tags.add(TDRC(encoding=3, text=[str(year)]))
        audio.tags.add(TRCK(encoding=3, text=[f"{track_number}/{total_tracks}"]))

        if img_data:
            audio.tags.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,  # Cover (front)
                desc="Front Cover",
                data=img_data,
            ))
        audio.save()

    elif ext in [".m4a", ".mp4"]:
        audio = MP4(file_path)
        audio["\xa9nam"] = [title]
        audio["\xa9ART"] = [artists]
        audio["\xa9alb"] = [album]
        if year:
            audio["\xa9day"] = [str(year)]
        audio["trkn"] = [(track_number, total_tracks)]
        if img_data:
            audio["covr"] = [MP4Cover(img_data, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()

    elif ext == ".flac":
        audio = FLAC(file_path)
        audio["TITLE"] = title
        audio["ARTIST"] = artists
        audio["ALBUM"] = album
        if year:
            audio["DATE"] = str(year)
        audio["TRACKNUMBER"] = str(track_number)
        audio["TRACKTOTAL"] = str(total_tracks)

        if img_data:
            picture = Picture()
            picture.type = 3
            picture.mime = "image/jpeg"
            picture.desc = "Front Cover"
            picture.data = img_data
            audio.clear_pictures()
            audio.add_picture(picture)
        audio.save()


class DownloadManager:
    """
    Manages active download queue, status reporting, and cancellation.
    """

    def __init__(self):
        self.active_job: Optional[Dict[str, Any]] = None
        self._cancel_flag = False
        self._lock = threading.Lock()
        self.subscribers: List[asyncio.Queue] = []

    def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """Notifies connected SSE listeners of progress updates."""
        payload = {"type": event_type, "data": data}
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def cancel_current_job(self):
        """Signals active downloads to abort."""
        with self._lock:
            self._cancel_flag = True
            if self.active_job:
                self.active_job["status"] = "cancelled"
        self.broadcast_event("job_cancelled", {"message": "Download cancelled by user."})

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancel_flag

    def start_download_job(
        self,
        playlist_title: str,
        tracks: List[Dict[str, Any]],
        options: Dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ):
        """Starts the download job in a background worker thread."""
        with self._lock:
            self._cancel_flag = False
            self.active_job = {
                "playlist_title": playlist_title,
                "status": "running",
                "total": len(tracks),
                "completed": 0,
                "failed": 0,
                "tracks": {t["id"]: {"status": "queued", "progress": 0, "message": "Queued"} for t in tracks},
                "options": options,
                "output_dir": options.get("output_dir", ""),
            }

        thread = threading.Thread(
            target=self._run_job_worker,
            args=(playlist_title, tracks, options, loop),
            daemon=True,
        )
        thread.start()

    def _run_job_worker(
        self,
        playlist_title: str,
        tracks: List[Dict[str, Any]],
        options: Dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ):
        output_dir = options.get("output_dir", "")
        if not output_dir:
            user_music = os.path.join(os.path.expanduser("~"), "Music", "Spotify Downloads")
            output_dir = os.path.join(user_music, sanitize_filename(playlist_title))

        os.makedirs(output_dir, exist_ok=True)
        audio_format = options.get("audio_format", "mp3").lower()
        bitrate = options.get("bitrate", "320")
        filename_format = options.get("filename_format", "{artist} - {title}")
        create_m3u8 = options.get("create_m3u8", True)
        overwrite = options.get("overwrite", False)

        downloaded_files: List[Tuple[str, str, int]] = []  # (filename, title, duration_seconds)
        total_tracks = len(tracks)

        # Concurrency setting (default 3, clamped between 1 and 8 for stability & speed)
        concurrency = int(options.get("concurrency", 3))
        concurrency = max(1, min(8, concurrency))

        downloaded_dict: Dict[int, Tuple[str, str, int]] = {}
        dict_lock = threading.Lock()
        job_start_time = time.time()
        track_bytes_downloaded: Dict[str, int] = {}
        bytes_lock = threading.Lock()

        with self._lock:
            if not self.active_job:
                self.active_job = {
                    "playlist_title": playlist_title,
                    "status": "running",
                    "total": total_tracks,
                    "completed": 0,
                    "failed": 0,
                    "tracks": {t["id"]: {"status": "queued", "progress": 0, "message": "Queued", "title": t.get("title", "")} for t in tracks},
                    "options": options,
                    "output_dir": output_dir,
                }

        def broadcast_progress_snapshot():
            now = time.time()
            elapsed = max(1.0, now - job_start_time)
            with bytes_lock:
                total_bytes = sum(track_bytes_downloaded.values())

            speed_bps = total_bytes / elapsed
            if speed_bps >= 1024 * 1024:
                speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s"
            else:
                speed_str = f"{speed_bps / 1024:.0f} KB/s"

            with self._lock:
                if not self.active_job:
                    return
                completed = self.active_job["completed"]
                failed = self.active_job["failed"]
                done_count = completed + failed
                overall_pct = int((done_count / total_tracks) * 100) if total_tracks > 0 else 0
                active_workers = [
                    t.get("title", "Track")
                    for t in self.active_job["tracks"].values()
                    if t.get("status") in ("searching", "downloading", "tagging")
                ]

            if done_count > 0 and done_count < total_tracks:
                sec_per_track = elapsed / done_count
                rem_seconds = int(sec_per_track * (total_tracks - done_count))
                if rem_seconds >= 60:
                    eta_str = f"~{rem_seconds // 60}m {rem_seconds % 60}s"
                else:
                    eta_str = f"~{rem_seconds}s"
            elif done_count >= total_tracks:
                eta_str = "Complete"
            else:
                eta_str = "Calculating..."

            loop.call_soon_threadsafe(
                self.broadcast_event,
                "job_progress",
                {
                    "completed": completed,
                    "failed": failed,
                    "total": total_tracks,
                    "percent": overall_pct,
                    "speed": speed_str,
                    "eta": eta_str,
                    "elapsed": int(elapsed),
                    "active_count": len(active_workers),
                    "active_tracks": active_workers[:3],
                },
            )

        def download_single_track(item: Tuple[int, Dict[str, Any]]):
            idx, track = item
            if self.is_cancelled():
                return

            track_id = track["id"]
            track_title = track.get("title", "Unknown Track")
            track_artists = track.get("artists", "Unknown Artist")
            album_name = track.get("album") or playlist_title or "Spotify"
            year = track.get("year", "")
            cover_url = track.get("cover_url", "")
            duration_ms = track.get("duration_ms", 0)

            # Stagger startup slightly to avoid sudden bursts hitting rate limits
            if concurrency > 1:
                time.sleep((idx % concurrency) * 0.2)

            # Build target filename
            clean_title = sanitize_filename(track_title)
            clean_artist = sanitize_filename(track_artists)
            if filename_format == "{track_number} - {artist} - {title}":
                filename = f"{idx:02d} - {clean_artist} - {clean_title}.{audio_format}"
            else:
                filename = f"{clean_artist} - {clean_title}.{audio_format}"

            final_filepath = os.path.join(output_dir, filename)

            # Check if file already exists
            if os.path.exists(final_filepath) and not overwrite:
                with self._lock:
                    self.active_job["completed"] += 1
                    self.active_job["tracks"][track_id] = {
                        "status": "completed",
                        "progress": 100,
                        "message": "Already downloaded",
                        "filename": filename,
                        "filepath": final_filepath,
                        "title": track_title,
                    }
                with dict_lock:
                    downloaded_dict[idx] = (filename, f"{track_artists} - {track_title}", duration_ms // 1000)

                loop.call_soon_threadsafe(
                    self.broadcast_event,
                    "track_update",
                    {"track_id": track_id, "status": "completed", "progress": 100, "message": "Already exists (skipped)", "filepath": final_filepath, "filename": filename},
                )
                broadcast_progress_snapshot()
                return

            # Notify: Searching
            with self._lock:
                self.active_job["tracks"][track_id] = {
                    "status": "searching",
                    "progress": 10,
                    "message": "Finding best audio stream...",
                    "title": track_title,
                }
            loop.call_soon_threadsafe(
                self.broadcast_event,
                "track_update",
                {"track_id": track_id, "status": "searching", "progress": 10, "message": "Finding best audio stream..."},
            )
            broadcast_progress_snapshot()

            try:
                temp_tmpl = os.path.join(output_dir, f"temp_{track_id}.%(ext)s")

                def ydl_progress_hook(d):
                    if d.get("status") == "downloading":
                        total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        downloaded_bytes = d.get("downloaded_bytes") or 0
                        with bytes_lock:
                            track_bytes_downloaded[track_id] = downloaded_bytes
                        if total_bytes > 0:
                            pct = int((downloaded_bytes / total_bytes) * 70) + 15
                            loop.call_soon_threadsafe(
                                self.broadcast_event,
                                "track_update",
                                {
                                    "track_id": track_id,
                                    "status": "downloading",
                                    "progress": pct,
                                    "message": f"Downloading audio {pct}%",
                                },
                            )
                        broadcast_progress_snapshot()

                from setup_ffmpeg import ensure_ffmpeg
                ffmpeg_bin, _ = ensure_ffmpeg()
                ffmpeg_dir = os.path.dirname(ffmpeg_bin) if ffmpeg_bin else None

                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": temp_tmpl,
                    "noplaylist": True,
                    "progress_hooks": [ydl_progress_hook],
                    "ffmpeg_location": ffmpeg_dir,
                    "concurrent_fragment_downloads": 4,
                    "http_chunk_size": 10485760,
                    "buffersize": 1024 * 64,
                    "retries": 2,
                    "fragment_retries": 2,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": audio_format,
                            "preferredquality": bitrate,
                        }
                    ],
                    "quiet": True,
                    "no_warnings": True,
                }

                temp_converted = os.path.join(output_dir, f"temp_{track_id}.{audio_format}")

                # Multi-Strategy Search & Fallback Pipeline (YouTube + SoundCloud Bot-Proof Engine)
                search_queries = [
                    f"ytsearch1:{track_artists} - {track_title} official audio",
                    f"scsearch1:{track_artists} - {track_title}",
                    f"ytsearch1:{track_artists} - {track_title}",
                    f"scsearch1:{track_title}",
                ]

                download_success = False
                for q in search_queries:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([q])
                        if os.path.exists(temp_converted):
                            download_success = True
                            break
                    except Exception:
                        continue

                if not download_success or not os.path.exists(temp_converted):
                    raise RuntimeError(f"Could not extract audio stream for '{track_title}'.")

                # Move temp to final filename
                if os.path.exists(final_filepath):
                    os.remove(final_filepath)
                shutil.move(temp_converted, final_filepath)

                # Tagging phase
                loop.call_soon_threadsafe(
                    self.broadcast_event,
                    "track_update",
                    {"track_id": track_id, "status": "tagging", "progress": 90, "message": "Embedding metadata & cover art..."},
                )

                embed_metadata(
                    file_path=final_filepath,
                    title=track_title,
                    artists=track_artists,
                    album=album_name,
                    year=year,
                    track_number=idx,
                    total_tracks=total_tracks,
                    cover_url=cover_url,
                    audio_format=audio_format,
                    embed_artwork=self.options.get("embed_artwork", True),
                )

                with self._lock:
                    self.active_job["completed"] += 1
                    self.active_job["tracks"][track_id] = {
                        "status": "completed",
                        "progress": 100,
                        "message": "Complete",
                        "filename": filename,
                        "filepath": final_filepath,
                        "title": track_title,
                    }

                with dict_lock:
                    downloaded_dict[idx] = (filename, f"{track_artists} - {track_title}", duration_ms // 1000)

                loop.call_soon_threadsafe(
                    self.broadcast_event,
                    "track_update",
                    {"track_id": track_id, "status": "completed", "progress": 100, "message": "Downloaded & Tagged", "filepath": final_filepath, "filename": filename},
                )
                broadcast_progress_snapshot()

            except Exception as err:
                with self._lock:
                    self.active_job["failed"] += 1
                    self.active_job["tracks"][track_id] = {
                        "status": "failed",
                        "progress": 0,
                        "message": f"Error: {str(err)}",
                        "title": track_title,
                    }
                loop.call_soon_threadsafe(
                    self.broadcast_event,
                    "track_update",
                    {"track_id": track_id, "status": "failed", "progress": 0, "message": str(err)},
                )
                broadcast_progress_snapshot()

        # Run concurrent downloads safely with ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(download_single_track, (idx, track)) for idx, track in enumerate(tracks, 1)]
            for future in concurrent.futures.as_completed(futures):
                if self.is_cancelled():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

        # Generate .m3u8 playlist file in exact original playlist order
        sorted_files = [downloaded_dict[k] for k in sorted(downloaded_dict.keys())]
        if create_m3u8 and sorted_files:
            try:
                m3u8_path = os.path.join(output_dir, f"{sanitize_filename(playlist_title)}.m3u8")
                with open(m3u8_path, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    for fname, name, dur in sorted_files:
                        f.write(f"#EXTINF:{dur},{name}\n")
                        f.write(f"{fname}\n")
            except Exception as e:
                print(f"[Warning writing M3U8] {e}", file=sys.stderr)

        with self._lock:
            if not self._cancel_flag:
                self.active_job["status"] = "completed"

        loop.call_soon_threadsafe(
            self.broadcast_event,
            "job_finished",
            {
                "status": self.active_job["status"],
                "completed": self.active_job["completed"],
                "failed": self.active_job["failed"],
                "total": total_tracks,
                "output_dir": output_dir,
                "elapsed_seconds": int(time.time() - job_start_time),
                "m3u8_file": m3u8_path if (create_m3u8 and sorted_files) else "",
            },
        )


# Global singleton manager
download_manager = DownloadManager()
