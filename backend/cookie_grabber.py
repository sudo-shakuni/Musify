"""
Spotify Cookie Grabber & Auto Token Extractor.
Automatically reads the sp_dc cookie from Chrome/Edge browser databases,
uses it to obtain a valid Spotify access token, and connects to My-Music.

This provides true 1-click hassle-free Spotify authentication.
"""

import base64
import json
import os
import shutil
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import requests

# Windows DPAPI for decrypting Chrome/Edge cookie encryption key
try:
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def _dpapi_decrypt(encrypted: bytes) -> bytes:
        blob_in = DATA_BLOB(len(encrypted), ctypes.create_string_buffer(encrypted, len(encrypted)))
        blob_out = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return data
        raise OSError("DPAPI CryptUnprotectData failed")

    HAS_DPAPI = True
except Exception:
    HAS_DPAPI = False


# AES-GCM decryption for Chromium v80+ cookies
try:
    from Crypto.Cipher import AES
    HAS_AES = True
except ImportError:
    try:
        from Cryptodome.Cipher import AES
        HAS_AES = True
    except ImportError:
        HAS_AES = False


# Browser profiles to scan (ordered by likelihood of having Spotify session)
BROWSER_PROFILES: List[Dict[str, str]] = []
_local = os.environ.get("LOCALAPPDATA", "")
_roaming = os.environ.get("APPDATA", "")

if _local:
    BROWSER_PROFILES.extend([
        {"name": "Chrome", "cookies": os.path.join(_local, "Google", "Chrome", "User Data", "Default", "Network", "Cookies"),
         "local_state": os.path.join(_local, "Google", "Chrome", "User Data", "Local State")},
        {"name": "Chrome (Profile 1)", "cookies": os.path.join(_local, "Google", "Chrome", "User Data", "Profile 1", "Network", "Cookies"),
         "local_state": os.path.join(_local, "Google", "Chrome", "User Data", "Local State")},
        {"name": "Edge", "cookies": os.path.join(_local, "Microsoft", "Edge", "User Data", "Default", "Network", "Cookies"),
         "local_state": os.path.join(_local, "Microsoft", "Edge", "User Data", "Local State")},
        {"name": "Edge (Profile 1)", "cookies": os.path.join(_local, "Microsoft", "Edge", "User Data", "Profile 1", "Network", "Cookies"),
         "local_state": os.path.join(_local, "Microsoft", "Edge", "User Data", "Local State")},
        {"name": "Brave", "cookies": os.path.join(_local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Network", "Cookies"),
         "local_state": os.path.join(_local, "BraveSoftware", "Brave-Browser", "User Data", "Local State")},
        {"name": "Vivaldi", "cookies": os.path.join(_local, "Vivaldi", "User Data", "Default", "Network", "Cookies"),
         "local_state": os.path.join(_local, "Vivaldi", "User Data", "Local State")},
        {"name": "Opera", "cookies": os.path.join(_roaming, "Opera Software", "Opera Stable", "Network", "Cookies"),
         "local_state": os.path.join(_roaming, "Opera Software", "Opera Stable", "Local State")},
        {"name": "Opera GX", "cookies": os.path.join(_roaming, "Opera Software", "Opera GX Stable", "Network", "Cookies"),
         "local_state": os.path.join(_roaming, "Opera Software", "Opera GX Stable", "Local State")},
    ])


def _get_chromium_master_key(local_state_path: str) -> Optional[bytes]:
    """Extracts and decrypts the AES master key from Chromium's Local State."""
    if not HAS_DPAPI or not HAS_AES:
        return None
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        b64_key = local_state["os_crypt"]["encrypted_key"]
        encrypted_key = base64.b64decode(b64_key)
        # Strip "DPAPI" prefix (5 bytes)
        if encrypted_key[:5] == b"DPAPI":
            encrypted_key = encrypted_key[5:]
        return _dpapi_decrypt(encrypted_key)
    except Exception as e:
        print(f"[CookieGrabber] Could not extract master key from {local_state_path}: {e}")
        return None


def _decrypt_cookie_value(encrypted_value: bytes, master_key: Optional[bytes]) -> str:
    """Decrypts a Chromium cookie value."""
    if not encrypted_value:
        return ""

    # v10/v20 prefix = AES-256-GCM encrypted (Chromium 80+)
    if encrypted_value[:3] in (b"v10", b"v20") and master_key and HAS_AES:
        try:
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:]
            cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext[:-16], ciphertext[-16:]).decode("utf-8")
        except Exception:
            pass

    # Legacy DPAPI-only encryption
    if HAS_DPAPI:
        try:
            return _dpapi_decrypt(encrypted_value).decode("utf-8")
        except Exception:
            pass

    return ""


def _copy_locked_file(src: str, dst: str) -> bool:
    """Copy a file that may be locked by another process (e.g. browser)."""
    # Strategy 1: Direct copy (works if browser isn't running)
    try:
        shutil.copy2(src, dst)
        return True
    except (PermissionError, OSError):
        pass

    # Strategy 2: Raw binary read (bypasses some file locks on Windows)
    try:
        with open(src, "rb") as f_in:
            data = f_in.read()
        with open(dst, "wb") as f_out:
            f_out.write(data)
        return True
    except (PermissionError, OSError):
        pass

    # Strategy 3: Windows Volume Shadow Copy via robocopy (handles hard locks)
    try:
        import subprocess
        src_dir = os.path.dirname(src)
        src_name = os.path.basename(src)
        dst_dir = os.path.dirname(dst)
        result = subprocess.run(
            ["robocopy", src_dir, dst_dir, src_name, "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np"],
            capture_output=True, timeout=5
        )
        # robocopy returns 0-7 for success, 8+ for errors
        if result.returncode < 8 and os.path.exists(dst):
            return True
    except Exception:
        pass

    return False


def _extract_sp_dc_from_db(cookies_path: str, master_key: Optional[bytes]) -> Optional[str]:
    """Reads sp_dc cookie from a Chromium SQLite cookie database."""
    if not os.path.exists(cookies_path):
        return None

    # Copy to temp file (browser may have the DB locked)
    tmp_dir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmp_dir, "Cookies_copy")
    try:
        if not _copy_locked_file(cookies_path, tmp_db):
            print(f"[CookieGrabber] Could not copy locked DB: {cookies_path}")
            return None

        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT encrypted_value, value FROM cookies "
            "WHERE host_key LIKE '%spotify.com' AND name = 'sp_dc' "
            "ORDER BY expires_utc DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            encrypted_value, plain_value = row
            if plain_value:
                return plain_value
            if encrypted_value:
                decrypted = _decrypt_cookie_value(encrypted_value, master_key)
                if decrypted and len(decrypted) > 20:
                    return decrypted
        return None
    except Exception as e:
        print(f"[CookieGrabber] Error reading {cookies_path}: {e}")
        return None
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def grab_sp_dc_cookie() -> Tuple[Optional[str], str]:
    """
    Scans all installed Chromium browsers for a valid sp_dc Spotify session cookie.
    Returns (sp_dc_value, browser_name) or (None, error_message).
    """
    if not HAS_DPAPI:
        return None, "Windows DPAPI not available (required for cookie decryption)"
    if not HAS_AES:
        return None, "pycryptodome not installed (required for cookie decryption)"

    for profile in BROWSER_PROFILES:
        cookies_path = profile["cookies"]
        local_state_path = profile["local_state"]
        browser_name = profile["name"]

        if not os.path.exists(cookies_path):
            continue

        master_key = _get_chromium_master_key(local_state_path)
        sp_dc = _extract_sp_dc_from_db(cookies_path, master_key)

        if sp_dc and len(sp_dc) > 20:
            print(f"[CookieGrabber] Found valid sp_dc cookie in {browser_name}")
            return sp_dc, browser_name

    return None, "No Spotify session found in any browser. Please log into open.spotify.com in Chrome or Edge first."


def exchange_sp_dc_for_token(sp_dc: str) -> Dict[str, Any]:
    """
    Uses the sp_dc cookie to obtain a valid Spotify Web Player access token.
    This is the same mechanism the Spotify Web Player uses internally.
    """
    url = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://open.spotify.com/",
        "Origin": "https://open.spotify.com",
        "Cookie": f"sp_dc={sp_dc}"
    }

    import urllib.request
    import json
    
    req = urllib.request.Request(url, headers=headers)
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            resp_body = response.read().decode('utf-8')
            status_code = response.status
    except urllib.error.HTTPError as e:
        status_code = e.code
        resp_body = e.read().decode('utf-8')
    except Exception as e:
        raise ValueError(f"Failed to connect to Spotify: {e}")

    if status_code != 200:
        print(f"[Auth Error] Spotify API returned {status_code}: {resp_body[:200]}")
        raise ValueError(f"Spotify rejected the session cookie (HTTP {status_code}). "
                         "Your Spotify session may have expired or the cookie was copied incorrectly. Please log into open.spotify.com and copy sp_dc again.")

    try:
        data = json.loads(resp_body)
    except Exception:
        raise ValueError("Spotify returned invalid JSON data.")
    access_token = data.get("accessToken")
    if not access_token:
        raise ValueError("Spotify returned empty access token. Your session cookie may be invalid or expired.")

    is_anonymous = data.get("isAnonymous", True)
    if is_anonymous:
        raise ValueError("Token is anonymous (not linked to your account). "
                         "Please log into open.spotify.com in your browser first.")

    return {
        "access_token": access_token,
        "expires_in": data.get("accessTokenExpirationTimestampMs", 0),
        "is_anonymous": is_anonymous,
        "client_id": data.get("clientId", ""),
    }


def auto_grab_and_authenticate() -> Dict[str, Any]:
    """
    Complete 1-click flow: grab sp_dc from browser → exchange for token → return token info.
    """
    sp_dc, source = grab_sp_dc_cookie()
    if not sp_dc:
        raise ValueError(source)

    token_data = exchange_sp_dc_for_token(sp_dc)
    token_data["source_browser"] = source
    return token_data
