import hashlib
import json
import os
import shlex
import ssl
import subprocess
import sys
import urllib.request

import truststore

from config import CONFIG_DIR, MAC, WIN

REPO = "arocafull00/colloquia"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
UPDATES_DIR = os.path.join(CONFIG_DIR, "updates")


def current_version():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _parse(version):
    try:
        return tuple(int(p) for p in version.lstrip("v").split("."))
    except ValueError:
        return ()


def _open(url, accept="application/octet-stream"):
    req = urllib.request.Request(url, headers={"User-Agent": "Colloquia-Updater", "Accept": accept})
    return urllib.request.urlopen(req, timeout=30, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))


def _appimage():
    return os.environ.get("APPIMAGE")


def _bundle():
    exe_dir = os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(exe_dir)) if exe_dir.endswith(".app/Contents/MacOS") else None


def _suffix():
    if not getattr(sys, "frozen", False):
        return None
    if WIN:
        return "-windows-setup.exe"
    if MAC:
        return "-macos-arm64.dmg" if _bundle() else None
    return "-linux-x86_64.AppImage" if _appimage() else None


def check():
    current = current_version()
    if not current:
        return None
    with _open(LATEST, "application/vnd.github+json") as r:
        release = json.load(r)
    latest = release.get("tag_name", "")
    if _parse(latest) <= _parse(current):
        return None
    info = {"version": latest.lstrip("v"), "page": release.get("html_url"), "asset": None}
    suffix = _suffix()
    for asset in release.get("assets", []):
        if suffix and asset["name"].endswith(suffix):
            info["asset"] = asset
    return info


def _target(asset):
    if _appimage():
        return _appimage() + ".update"
    os.makedirs(UPDATES_DIR, exist_ok=True)
    return os.path.join(UPDATES_DIR, asset["name"])


def download(info, progress):
    asset = info["asset"]
    dest = _target(asset)
    expected = (asset.get("digest") or "").removeprefix("sha256:")
    if os.path.exists(dest) and os.path.getsize(dest) == asset.get("size"):
        return dest
    for old in os.listdir(UPDATES_DIR) if os.path.isdir(UPDATES_DIR) else []:
        os.remove(os.path.join(UPDATES_DIR, old))
    tmp = dest + ".part"
    sha = hashlib.sha256()
    with _open(asset["browser_download_url"]) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    if expected and sha.hexdigest() != expected:
        os.remove(tmp)
        raise ValueError("La descarga de la actualización está dañada.")
    os.replace(tmp, dest)
    return dest


def _after_exit(script, *args):
    pid = str(os.getpid())
    cmd = f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done; {script}"
    subprocess.Popen(["/bin/sh", "-c", cmd, "updater", *args], start_new_session=True)


def install(path, relaunch):
    if WIN:
        flags = "/SILENT" if relaunch else "/VERYSILENT"
        args = f'{flags} /SUPPRESSMSGBOXES /NORESTART' + (" /RELAUNCH=1" if relaunch else "")
        subprocess.Popen(
            f'cmd /c "ping -n 3 127.0.0.1 >nul & "{path}" {args}"',
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    elif MAC:
        script = (
            'mnt=$(mktemp -d) && hdiutil attach -nobrowse -readonly -mountpoint "$mnt" "$1" >/dev/null || exit 1; '
            'rm -rf "$2.new" && ditto "$mnt/Colloquia.app" "$2.new" && rm -rf "$2" && mv "$2.new" "$2"; '
            'hdiutil detach "$mnt" >/dev/null; rm -f "$1"; xattr -dr com.apple.quarantine "$2" 2>/dev/null; '
            '[ "$3" = 1 ] && open "$2"'
        )
        _after_exit(script, path, _bundle(), "1" if relaunch else "0")
    else:
        appimage = _appimage()
        os.chmod(path, 0o755)
        os.replace(path, appimage)
        if relaunch:
            _after_exit(f"exec {shlex.quote(appimage)}")
