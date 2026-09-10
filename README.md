# 🎵 Spotify Playlist Cloner & Downloader

A full-featured, zero-cost desktop & web application to preview, clone, and download Spotify playlists with studio-grade audio quality and complete authentic metadata (track title, contributing artists, album, high-resolution cover artwork, release year, track numbering, and `.m3u8` playlist cloning).

![Interface Preview](https://community.spotify.com/t5/image/serverpage/image-id/25294i2836BD1C1A311FFE/image-size/large?v=v2&px=999)

---

## ✨ Features

- **Zero Paid Subscriptions or API Keys Needed**:
  - Automatically fetches playlist and track details from Spotify's public web architecture.
  - Matches songs against YouTube Music / YouTube high-bitrate audio streams.
- **Authentic ID3 & Audio Metadata**:
  - Track Title (`TIT2`)
  - Artists & Album Artist (`TPE1`, `TPE2`)
  - Album Name (`TALB`)
  - Release Year / Date (`TDRC`)
  - Track Number & Total Count (`TRCK`)
  - Embedded High-Resolution Album Artwork (`APIC` / `covr`)
- **Playlist Cloning (`.m3u8`)**:
  - Automatically generates an `.m3u8` playlist file in the downloaded folder so you can import the entire playlist in its original sequence directly into VLC, MusicBee, Foobar2000, or mobile music players.
- **Format & Bitrate Selection**:
  - MP3 (320 kbps, 256 kbps, 192 kbps, 128 kbps)
  - M4A / AAC (optimal for Apple devices)
  - FLAC (lossless audio container)
  - OPUS
- **Modern Spotify Dark-Themed Web UI**:
  - Live playlist preview with high-res cover art, curator details, and track table.
  - 30-second audio previews directly in your browser.
  - Cherry-pick specific songs or download the entire playlist with one click.
  - Live download dashboard with animated progress bar and per-track status badges.
  - "Open in Windows Explorer" button to jump right to your downloaded audio files.
- **Zero-Manual FFmpeg Configuration**:
  - FFmpeg is automatically resolved and configured via `static-ffmpeg`.

---

## 🚀 Quick Start (Windows)

### Option 1: One-Click Launcher
Simply double-click:
```text
run.bat
```
This script will:
1. Initialize the Python virtual environment.
2. Verify dependencies.
3. Configure the FFmpeg audio engine.
4. Launch the local web server and automatically open `http://localhost:8800` in your browser.

---

### Option 2: Manual Terminal Run
```bash
# 1. Navigate to the project folder
cd spotify-downloader

# 2. Activate virtual environment
.\.venv\Scripts\activate

# 3. Run the application
# Run native desktop application window
python desktop.py

# Or run as headless web server
python backend/main.py
```
Then visit `http://localhost:8800` in your web browser.

---

## 📋 How to Use

1. **Copy a Spotify Link**:
   - Open Spotify (desktop app or web player).
   - Right click any Playlist, Album, or Track -> `Share` -> `Copy link to playlist`.
2. **Paste & Load**:
   - Paste the link into the application's search bar.
   - Click **Load Playlist** (or select one of the quick samples).
3. **Customize Preferences (Optional)**:
   - Click the **Settings icon** (`⚙️`) in the top right.
   - Choose your audio format (MP3 320k, M4A, FLAC, OPUS).
   - Change the destination folder (defaults to your `Music/Spotify Downloads` folder).
4. **Download**:
   - Select the tracks you want to clone (all tracks are selected by default).
   - Click **Download Selected Tracks**.
   - Watch the real-time progress bar and status badges.
5. **Listen**:
   - Click **Open Folder** or double click the created `.m3u8` file to start listening immediately in any media player!

---

## 🛠️ Free Open-Source Stack

- **Python 3.14**: Backend runtime.
- **yt-dlp**: Ultra-fast audio stream matching and downloading engine.
- **FFmpeg**: Audio conversion and audio format remuxing.
- **Mutagen**: Deep ID3v2.4 and Vorbis/MP4 metadata tagger.
- **FastAPI & Uvicorn**: Asynchronous backend server with Server-Sent Events (SSE).
- **Lucide Icons & Tailwind CSS Philosophy**: Responsive Spotify Dark UI.

---

## 📂 Project Structure

```text
spotify-downloader/
├── backend/
│   ├── downloader.py       # Audio downloader, conversion, and mutagen tagging engine
│   ├── spotify_meta.py     # Spotify public embed metadata resolver
│   └── main.py             # FastAPI backend with REST & SSE endpoints
├── frontend/
│   ├── index.html          # Spotify Dark UI interface
│   ├── style.css           # Modern styles, animations, and dark theme
│   └── app.js              # Frontend state, event listeners, and SSE controller
├── run.bat                 # One-click Windows launcher
├── setup_ffmpeg.py         # Automatic FFmpeg path resolver
├── requirements.txt        # Python dependency manifest
└── README.md               # Documentation
```
