"""
FFmpeg setup and path resolver for Spotify Downloader.
Ensures FFmpeg is available on Windows without manual user installation.
"""

import os
import shutil
import subprocess
import sys


def ensure_ffmpeg() -> tuple[str, str]:
    """
    Ensures FFmpeg and FFprobe binaries are available in PATH.
    Returns (ffmpeg_path, ffprobe_path).
    """
    # 1. Check if ffmpeg is already in standard PATH
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe

    # 2. Check local bin/ folder
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_bin = os.path.join(base_dir, "bin")
    if os.path.exists(local_bin):
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg and ffprobe:
            return ffmpeg, ffprobe

    # 3. Use static_ffmpeg to provide binaries
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg and ffprobe:
            return ffmpeg, ffprobe
    except Exception as e:
        print(f"[Warning] Failed to initialize static_ffmpeg: {e}", file=sys.stderr)

    return shutil.which("ffmpeg") or "ffmpeg", shutil.which("ffprobe") or "ffprobe"


if __name__ == "__main__":
    ffmpeg, ffprobe = ensure_ffmpeg()
    print(f"FFmpeg binary: {ffmpeg}")
    print(f"FFprobe binary: {ffprobe}")
    res = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True)
    if res.returncode == 0:
        print("FFmpeg is verified and working!")
    else:
        print("FFmpeg failed to run.", file=sys.stderr)
