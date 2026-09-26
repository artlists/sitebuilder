#!/usr/bin/env python3
"""SiteBuilder desktop launcher — one-click constructor server.

Bundles the engine (build.py, template.html, admin/) plus a clean starter
data.json.  On first run it copies them into a per-user workspace, generates
an admin password, starts the local admin server and opens the browser.

Run:  python3 app/launcher.py
"""

import base64
import hashlib
import json
import os
import pathlib
import secrets
import socket
import sys
import threading
import time
import webbrowser

APP_NAME = "SiteBuilder"
HOST, PORT = "127.0.0.1", 8899
if os.environ.get("SBHOST"):
    HOST = os.environ["SBHOST"]
if os.environ.get("SBPORT"):
    PORT = int(os.environ["SBPORT"])


def resource_root():
    """Engine files live either next to this script (dev) or inside the
    PyInstaller bundle (_MEIPASS)."""
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        return pathlib.Path(mp)
    return pathlib.Path(__file__).resolve().parent.parent


def workspace_root():
    override = os.environ.get("SBWORKSPACE", "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    home = pathlib.Path.home()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", home)
    else:
        base = home
    return base / ("SiteBuilder" if sys.platform != "win32" else "SiteBuilder")


def ensure_workspace():
    src = resource_root()
    engine = src / "engine"
    starter = src / "starter"
    ws = workspace_root()
    ws.mkdir(parents=True, exist_ok=True)
    admin_dir = ws / "admin"
    admin_dir.mkdir(parents=True, exist_ok=True)

    # engine files -> workspace (idempotent, overwrites engine only)
    for name in ("build.py", "template.html"):
        shutil_copy(engine / name, ws / name)
    shutil_copy(engine / "admin" / "server.py", admin_dir / "server.py")
    shutil_copy(engine / "admin" / "publish.sh", admin_dir / "publish.sh")
    shutil_copy(engine / "admin" / "init_password.py", admin_dir / "init_password.py")
    static = admin_dir / "static"
    static.mkdir(parents=True, exist_ok=True)
    for f in ("admin.html", "admin.css", "admin.js"):
        shutil_copy(engine / "admin" / "static" / f, static / f)

    # starter data (only if missing, so user data is never overwritten)
    data_file = ws / "data.json"
    if not data_file.exists():
        shutil_copy(starter / "data.json", data_file)

    # per-instance registry: single default site living inside the workspace
    reg_file = admin_dir / "sites.json"
    if not reg_file.exists():
        reg = {
            "default": "site",
            "sites": {
                "site": {
                    "title": "My Site",
                    "data": "data.json",
                    "site": "site",
                    "secrets": "admin/secrets.env",
                    "log": "admin/publish.log",
                    "history": "admin/deploy_history.json",
                }
            },
        }
        reg_file.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

    secrets_file = admin_dir / "secrets.env"
    if not secrets_file.exists():
        secrets_file.write_text("# deploy tokens go here (Deploy tab)\n", encoding="utf-8")

    # admin user with a freshly generated password (kept across runs)
    users_file = admin_dir / "users.json"
    cred_file = ws / "ADMIN-CREDENTIALS.txt"
    if not users_file.exists():
        password = secrets.token_urlsafe(12)
        users_file.write_text(
            json.dumps([{
                "username": "admin",
                "hash": _hash_password(password),
            }], indent=2), encoding="utf-8")
        cred_file.write_text(
            f"SiteBuilder admin\n\nURL:      http://{HOST}:{PORT}/admin\n"
            f"Username: admin\nPassword: {password}\n", encoding="utf-8")
        try:
            os.chmod(cred_file, 0o600)
        except OSError:
            pass
        print("First run: workspace created at", ws)
        print("Admin credentials saved to", cred_file)
        print(f"Username: admin / Password: {password}")
    return ws


def _hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return (f"pbkdf2_sha256${260_000}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}")


def shutil_copy(src, dst):
    import shutil
    if src.exists():
        shutil.copy2(src, dst)


def port_busy(host, port):
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def main():
    ws = ensure_workspace()
    if port_busy(HOST, PORT):
        print(f"admin already running on http://{HOST}:{PORT}/admin (port busy)")
        webbrowser.open(f"http://{HOST}:{PORT}/admin")
        return 0

    os.chdir(ws)
    sys.path.insert(0, str(ws))
    os.environ.setdefault("SBHOST", HOST)
    os.environ.setdefault("SBPORT", str(PORT))
    import admin.server as srv

    print(f"SiteBuilder admin: http://{HOST}:{PORT}/admin")
    print("Press Ctrl+C to stop.")

    def serve():
        srv.main()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    def open_browser():
        time.sleep(1.0)
        webbrowser.open(f"http://{HOST}:{PORT}/admin")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())