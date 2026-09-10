"""
Single Desktop Application for Spotify Playlist Cloner & Downloader.
Runs the backend in-process, opens a native desktop window,
and ensures complete process cleanup on exit.
"""
import os
import sys
import threading
import time
import urllib.request
import webbrowser

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import uvicorn
import webview

from backend.main import app
from setup_ffmpeg import ensure_ffmpeg

PORT = 8800


class ServerThread(threading.Thread):
    def __init__(self, port=PORT):
        super().__init__(daemon=True)
        self.port = port
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    ensure_ffmpeg()

    global PORT
    server = None

    already_running = False
    if is_port_in_use(PORT):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/system/info", timeout=1) as resp:
                if resp.status == 200:
                    already_running = True
        except Exception:
            PORT = 8801

    if not already_running:
        server = ServerThread(PORT)
        server.start()

        started = False
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/system/info", timeout=1)
                started = True
                break
            except Exception:
                time.sleep(0.1)

        if not started:
            print(f"[Warning] Backend server is taking longer than expected to initialize on port {PORT}")

    app_url = f"http://127.0.0.1:{PORT}"
    try:
        webview.create_window(
            title="Musify — Studio-Grade Music Downloader",
            url=app_url,
            width=1240,
            height=850,
            min_size=(960, 680),
            background_color="#121212",
        )
        webview.start()
    except Exception as e:
        print(f"[Musify Notice] Opening in web browser: {e}")
        print(f"Running at: {app_url}")
        print("Press Ctrl+C to close and exit.")
        webbrowser.open(app_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down Musify...")

    if server:
        server.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()

