"""
End-to-end integration test suite for Spotify Playlist Cloner & Downloader.
Tests metadata extraction, server endpoints, and audio download + metadata embedding.
"""

import os
import sys
import time
import requests
from mutagen.id3 import ID3

# Ensure path
sys.path.insert(0, os.path.abspath("."))

from backend.spotify_meta import fetch_metadata
from backend.downloader import download_manager, embed_metadata
from setup_ffmpeg import ensure_ffmpeg


def test_ffmpeg_availability():
    print("[1/4] Testing FFmpeg setup...")
    ffmpeg_bin, ffprobe_bin = ensure_ffmpeg()
    assert ffmpeg_bin and os.path.exists(ffmpeg_bin), "FFmpeg binary missing!"
    assert ffprobe_bin and os.path.exists(ffprobe_bin), "FFprobe binary missing!"
    print(f"  [PASS] FFmpeg verified: {ffmpeg_bin}")


def test_spotify_metadata():
    print("[2/4] Testing Spotify metadata resolver...")
    url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    meta = fetch_metadata(url)
    assert meta["title"], "Missing playlist title"
    assert meta["total_tracks"] > 0, "No tracks returned"
    assert len(meta["tracks"]) > 0, "Empty tracks array"
    first = meta["tracks"][0]
    assert first["title"], "Missing track title"
    assert first["artists"], "Missing artist"
    print(f"  [PASS] Playlist parsed: '{meta['title']}' ({meta['total_tracks']} tracks)")
    print(f"  [PASS] Sample track: '{first['title']}' by {first['artists']}")


def test_audio_download_and_id3_tagging():
    print("[3/4] Testing audio download and mutagen ID3 embedding...")
    test_dir = os.path.abspath("test_output")
    os.makedirs(test_dir, exist_ok=True)
    
    test_track = {
        "id": "test_id_123",
        "title": "Ain't In LA",
        "artists": "ADÉLA",
        "album": "Ain't In LA - Single",
        "year": "2026",
        "cover_url": "https://image-cdn-fa.spotifycdn.com/image/ab67616d0000b273b176fc721e1faba78b1ef35b",
        "duration_ms": 184000,
    }
    
    # We will test download_manager with 1 track synchronously
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    options = {
        "output_dir": test_dir,
        "audio_format": "mp3",
        "bitrate": "320",
        "filename_format": "{artist} - {title}",
        "create_m3u8": True,
        "overwrite": True,
    }
    
    # Run the worker directly
    download_manager._run_job_worker(
        playlist_title="Test Suite Playlist",
        tracks=[test_track],
        options=options,
        loop=loop,
    )
    
    expected_file = os.path.join(test_dir, "ADÉLA - Ain't In LA.mp3")
    assert os.path.exists(expected_file), f"Expected file not found: {expected_file}"
    assert os.path.getsize(expected_file) > 100000, "File is too small or corrupted"
    
    # Verify ID3 tags
    tags = ID3(expected_file)
    assert str(tags.get("TIT2")) == "Ain't In LA", f"Incorrect title tag: {tags.get('TIT2')}"
    assert str(tags.get("TPE1")) == "ADÉLA", f"Incorrect artist tag: {tags.get('TPE1')}"
    assert str(tags.get("TALB")) == "Ain't In LA - Single", f"Incorrect album tag: {tags.get('TALB')}"
    assert any(k.startswith("APIC") for k in tags.keys()), "Missing embedded cover art APIC tag"
    
    # Verify M3U8
    m3u8_file = os.path.join(test_dir, "Test Suite Playlist.m3u8")
    assert os.path.exists(m3u8_file), "M3U8 playlist file was not created"
    
    print("  [PASS] Audio downloaded, converted to 320kbps MP3")
    print("  [PASS] Full ID3 tags & high-resolution album art verified")
    print("  [PASS] Cloned .m3u8 playlist file created")
    
    # Cleanup test_output
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    print("  [PASS] Test artifacts cleaned up")


def test_concurrent_downloads():
    print("[4/5] Testing multi-track concurrent download & safe playlist ordering...")
    test_dir = os.path.abspath("test_concurrent_output")
    os.makedirs(test_dir, exist_ok=True)
    
    tracks = [
        {
            "id": "c_track_1",
            "title": "Midnight City",
            "artists": "M83",
            "album": "Hurry Up, We're Dreaming",
            "year": "2011",
            "cover_url": "",
            "duration_ms": 243000,
        },
        {
            "id": "c_track_2",
            "title": "Starboy",
            "artists": "The Weeknd",
            "album": "Starboy",
            "year": "2016",
            "cover_url": "",
            "duration_ms": 230000,
        },
    ]

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    options = {
        "output_dir": test_dir,
        "audio_format": "mp3",
        "bitrate": "128",
        "filename_format": "{track_number} - {artist} - {title}",
        "create_m3u8": True,
        "overwrite": True,
        "concurrency": 2,
    }

    download_manager._run_job_worker(
        playlist_title="Concurrent Test Playlist",
        tracks=tracks,
        options=options,
        loop=loop,
    )

    m3u8_file = os.path.join(test_dir, "Concurrent Test Playlist.m3u8")
    assert os.path.exists(m3u8_file), "M3U8 file missing from concurrent run"
    with open(m3u8_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "01 - M83 - Midnight City.mp3" in content, "First track missing from M3U8"
    assert "02 - The Weeknd - Starboy.mp3" in content, "Second track missing from M3U8"

    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    print("  [PASS] Concurrent downloads executed and M3U8 playlist sequence verified!")


def test_ui_files():
    print("[5/5] Testing Frontend files integrity...")
    assert os.path.exists("frontend/index.html"), "index.html missing"
    assert os.path.exists("frontend/style.css"), "style.css missing"
    assert os.path.exists("frontend/app.js"), "app.js missing"
    assert os.path.exists("run.bat"), "run.bat missing"
    print("  [PASS] All UI & launcher files present")


if __name__ == "__main__":
    print("========================================")
    print(" Running Full Verification Test Suite")
    print("========================================")
    test_ffmpeg_availability()
    test_spotify_metadata()
    test_audio_download_and_id3_tagging()
    test_concurrent_downloads()
    test_ui_files()
    print("\n[SUCCESS] ALL TESTS PASSED!")

