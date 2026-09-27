#!/usr/bin/env python3
"""Slut Online admin server — local-only, stdlib only.

Serves the admin UI and an HTTP JSON API that edits data.json, uploads
media into the site folder, and publishes (build + wrangler deploy).

Security:
  - binds 127.0.0.1 only
  - PBKDF2(hashlib) password hashes stored in admin/users.json (no plaintext)
  - login rate limit (10 tries / 60s per client, then 30s backoff)
  - HMAC-signed short-lived bearer tokens (no cookies -> no CSRF surface)

Run:  python3 admin/server.py   (from the engine folder)
"""
import base64
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
import build  # noqa: E402
ADMIN = ROOT / "admin"
INSTANCES_FILE = ADMIN / "sites.json"
USERS = ADMIN / "users.json"
SECRET_FILE = ADMIN / ".secret"
PUBLISH_SH = ADMIN / "publish.sh"
PUBLISH_STATUS = ADMIN / "publish.json"
STATIC = ADMIN / "static"

HOST, PORT = "127.0.0.1", 8899
# The packaged desktop app sets these so a second instance can be detected and
# the launcher can report the right URL.
if os.environ.get("SBHOST"):
    HOST = os.environ["SBHOST"]
if os.environ.get("SBPORT"):
    PORT = int(os.environ["SBPORT"])
TOKEN_TTL = 12 * 3600

# deploy providers -> the env var in secrets.env that holds its API key
PROVIDERS = ["cloudflare_pages", "github_pages", "netlify", "surge", "neocities"]
PROVIDER_SECRET = {
    "cloudflare_pages": "CLOUDFLARE_API_TOKEN",
    "github_pages": "GITHUB_TOKEN",
    "netlify": "NETLIFY_TOKEN",
    "surge": "SURGE_TOKEN",
    "neocities": "NEOCITIES_TOKEN",
}
DEPLOY_KEYS = ["provider", "project_name", "domain", "repo"]
PBKDF2_ITER = 260_000
RATE_MAX = 10
RATE_WINDOW = 60
RATE_BACKOFF = 30

MEDIA_EXT = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif",
    ".mp4", ".mov", ".webm",
    ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".wav", ".flac",
}
MIME = {
    ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".avif": "image/avif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".wav": "audio/wav",
    ".flac": "audio/flac", ".txt": "text/plain", ".woff2": "font/woff2",
}


def read_secrets(secrets_path):
    """Parse a secrets.env file into a dict (no exceptions, returns {})."""
    d = {}
    try:
        for line in secrets_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        return {}
    return d


def validate_deploy(inst):
    """Return a list of human-readable error strings for site's deploy config.

    Mirrors the fail-fast checks in admin/publish.sh.  Empty list == OK.
    """
    slug = inst.get("slug", "")
    dep = (_read_json(inst["data"], {}) or {}).get("deploy", {}) if inst["data"].exists() else {}
    secrets = read_secrets(inst["secrets"])
    provider = dep.get("provider", "cloudflare_pages")
    project = (dep.get("project_name") or os.environ.get("PROJECT_NAME") or "").strip()
    domain = (dep.get("domain") or "").strip()
    repo = (dep.get("repo") or "").strip()
    errs = []
    tab = f"Admin > switch to site '{slug}' > Deploy tab"
    if provider == "cloudflare_pages":
        if not secrets.get("CLOUDFLARE_API_TOKEN"):
            errs.append("CLOUDFLARE_API_TOKEN missing.  "
                        f"{tab} > paste your Cloudflare API token (Account.Read + Pages.Edit scope) into the Token field and press Save.")
        if not project:
            errs.append(f"project name empty.  {tab} > Project field — enter the name from dash.cloudflare.com exactly.  "
                        f"Hint: try '{slug}' (gives https://{slug}.pages.dev).")
    elif provider == "github_pages":
        if not secrets.get("GITHUB_TOKEN"):
            errs.append(f"GITHUB_TOKEN missing.  {tab} > Token (scope 'public_repo') > Save.")
        if not repo:
            errs.append(f"repo empty.  {tab} > Repo, format: user/repo.")
    elif provider == "netlify":
        if not secrets.get("NETLIFY_TOKEN"):
            errs.append(f"NETLIFY_TOKEN missing.  {tab} > Token > Save.")
    elif provider == "surge":
        if not secrets.get("SURGE_TOKEN"):
            errs.append(f"SURGE_TOKEN missing.  Run 'surge token' locally, paste result into {tab} > Token > Save.")
        if not domain:
            errs.append(f"domain empty.  {tab} > Domain, example: '{slug}.surge.sh'.")
    elif provider == "neocities":
        if not secrets.get("NEOCITIES_TOKEN"):
            errs.append(f"NEOCITIES_TOKEN missing.  {tab} > Token (Neocities API key) > Save.")
    return errs
MAX_UPLOAD = 200 * 1024 * 1024


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- instances ---------------------------------------------------------------
#
# admin/sites.json keeps every managed site on relative paths (resolved against
# ROOT). "default" points at the legacy instance, so the original site keeps
# working untouched while new sites live under sites/<slug>/.

def read_registry():
    reg = _read_json(INSTANCES_FILE, {})
    if not isinstance(reg, dict) or not isinstance(reg.get("sites"), dict):
        reg = {"default": "slutonline", "sites": {}}
    return reg


def write_registry(reg):
    _write_json(INSTANCES_FILE, reg)


def _resolve(rel):
    return (ROOT / rel).resolve()


def default_slug():
    reg = read_registry()
    return reg.get("default") if reg.get("default") in reg.get("sites", {}) else next(
        iter(reg.get("sites", {})), "slutonline")


def instance_paths(slug=""):
    reg = read_registry()
    name = slug if slug in reg.get("sites", {}) else default_slug()
    ent = reg.get("sites", {}).get(name)
    if not ent:
        return None
    return {
        "slug": name,
        "title": ent.get("title", name),
        "data": _resolve(ent.get("data") or "data.json"),
        "site": _resolve(ent.get("site") or "../slutonline"),
        "secrets": _resolve(ent.get("secrets") or "admin/secrets.env"),
        "log": _resolve(ent.get("log") or "admin/publish.log"),
        "history": _resolve(ent.get("history") or "admin/deploy_history.json"),
    }


def list_instances():
    reg = read_registry()
    return [{"slug": s, "title": e.get("title", s)}
            for s, e in reg.get("sites", {}).items()]


def get_secret():
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    s = secrets.token_hex(32)
    SECRET_FILE.write_text(s, encoding="utf-8")
    os.chmod(SECRET_FILE, 0o600)
    return s


SECRET = get_secret()


def read_secrets_env(path):
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def write_secrets_env(path, env):
    path.write_text(
        "".join(f"{k}={v}\n" for k, v in sorted(env.items())), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def users():
    return _read_json(USERS, [])


def verify_user(username, password):
    for u in users():
        if hmac.compare_digest(u.get("username", ""), username):
            return _verify_hash(u.get("hash", ""), password)
    return False


def _verify_hash(stored, password):
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iter_s))
        return len(expected) == len(got) and hmac.compare_digest(expected, got)
    except (ValueError, TypeError):
        return False


def _hash_password(password, iterate=260_000):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterate)
    return (f"pbkdf2_sha256${iterate}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}")


def change_password(username, new_password):
    current = users()
    for u in current:
        if u.get("username") == username:
            u["hash"] = _hash_password(new_password)
            break
    else:
        current.append({"username": username, "hash": _hash_password(new_password)})
    USERS.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(USERS, 0o600)
    except OSError:
        pass


def make_token(username):
    exp = int(time.time()) + TOKEN_TTL
    payload = json.dumps({"u": username, "exp": exp}, separators=(",", ":"))
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def check_token(token):
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(".", 1)
        expect = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        return data.get("u")
    except Exception:
        return None


# ---- data validation -------------------------------------------------------

SITE_KEYS = {"name", "logo_text", "bio_h2", "title", "domain", "hero",
             "og_image_width", "og_image_height", "locale", "favicon"}
SEO_KEYS = {"meta_description", "keywords", "og_description", "twitter_description",
            "job_title", "ld_description", "knows_about", "analytics_snippet"}
SOCIAL_KEYS = {"instagram_url", "instagram_handle", "bandcamp_url", "behance_url",
               "booking_label", "instagram_label", "bandcamp_label"}
MUSIC_KEYS = {"kind", "url", "img", "alt", "span", "credit"}
WATCH_KEYS = {"kind", "variant", "src", "poster", "caption", "credit"}
PRESS_KEYS = {"kind", "url", "img", "text", "credit"}
KINDS = {"music", "watch", "press"}
WATCH_VARIANTS = {"classic", "center", "portrait", "tall"}
PAGE_TYPES = {"gallery", "info"}

# seed used for legacy data (no "kinds" key) and as the default kind table; the
# full data-driven kind support replaces the constants above in the same shape.
DEFAULT_KINDS = {
    "music": {"label": "Music", "text": ["span"], "inputs": ["url", "img", "audio", "alt"],
              "required": ["img", "span"]},
    "watch": {"label": "Watch", "text": ["caption"], "inputs": ["src", "poster"],
              "variants": ["classic", "center", "portrait", "tall"],
              "required": ["variant", "src", "caption"]},
    "press": {"label": "Press", "text": ["text"], "inputs": ["url", "img"],
              "required": ["url", "img", "text"]},
    "news": {"label": "News", "text": ["span", "body"],
             "inputs": ["img", "link", "link_label"],
             "list": ["images"],
             "colors": ["credit_color", "span_color", "text_color"],
             "rich": ["body"],
             "required": ["img", "span"]},
}


def _starter_data(title):
    return {
        "site": {
            "name": title, "logo_text": title, "bio_h2": "About " + title,
            "title": title, "domain": "https://example.com", "hero": "",
            "og_image_width": 1200, "og_image_height": 630, "locale": "en_US",
            "favicon": "",
        },
        "seo": {"meta_description": f"{title} — portfolio", "keywords": "art",
                "og_description": "", "twitter_description": "", "job_title": "",
                "knows_about": []},
        "social": {"instagram_url": "https://instagram.com/",
                   "instagram_handle": "you",
                   "bandcamp_url": "https://you.bandcamp.com",
                   "booking_label": "Booking / shows:",
                   "instagram_label": "on Instagram",
                   "bandcamp_label": "music"},
        "deploy": {"provider": "cloudflare_pages", "project_name": "", "domain": "",
                   "repo": ""},
        "kinds": DEFAULT_KINDS,
        "pages": [
            {"id": "gallery", "label": "Gallery", "type": "gallery", "show_in_menu": True},
            {"id": "info", "label": "Info", "type": "info", "show_in_menu": True},
        ],
        "bio": [""],
    }


def _check_obj(obj, keys, required, extra_label):
    for k in keys:
        if k not in obj:
            obj[k] = ""
    for k in required:
        if not isinstance(obj.get(k, ""), str) or not obj[k].strip():
            raise ValueError(f"{extra_label}: missing required '{k}'")


def _check_items(items, label, kinds):
    if not isinstance(items, list):
        raise ValueError(f"{label} must be a list")
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"{label}[{i}]: must be an object")
        kind = it.get("kind", "")
        if not kind:  # legacy single-kind pages
            it["kind"] = "music"
            kind = "music"
        if kind not in kinds:
            raise ValueError(f"{label}[{i}]: bad kind '{kind}'")
        defn = kinds[kind]
        keys = ({"kind", "credit"}
                | set(defn.get("text", [])) | set(defn.get("inputs", [])))
        if defn.get("variants"):
            if it.get("variant") not in defn["variants"]:
                raise ValueError(f"{label}[{i}]: bad variant '{it.get('variant')}'")
        _check_obj(it, keys, defn.get("required", []), f"{label}[{i}]")


def validate_data(d):
    if not isinstance(d, dict):
        raise ValueError("data must be an object")
    site = d.get("site", {})
    _check_obj(site, SITE_KEYS, {"name", "logo_text", "bio_h2", "title", "domain"}, "site")
    if not isinstance(site.get("og_image_width"), int) or not isinstance(site.get("og_image_height"), int):
        raise ValueError("site: og_image_width/height must be ints")
    _check_obj(d.get("seo", {}), SEO_KEYS, {"meta_description", "keywords"}, "seo")
    if not isinstance(d.get("seo", {}).get("knows_about"), list):
        raise ValueError("seo.knows_about must be a list")
    _check_obj(d.get("social", {}), SOCIAL_KEYS,
               {"instagram_url", "instagram_handle"}, "social")

    kinds = d.get("kinds")
    if not isinstance(kinds, dict) or not kinds:
        kinds = DEFAULT_KINDS
    else:
        for kid, defn in kinds.items():
            if not isinstance(defn, dict):
                raise ValueError(f"kinds.{kid}: must be an object")
            for key in ("inputs", "text", "list", "colors", "rich"):
                v = defn.get(key)
                if v is None:
                    continue
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                    raise ValueError(f"kinds.{kid}: {key} must be a list of strings")
            if "variants" in defn and (not isinstance(defn["variants"], list)
                                       or not all(isinstance(x, str) for x in defn["variants"])):
                raise ValueError(f"kinds.{kid}: variants must be a list of strings")
            req = defn.get("required")
            if req is not None and (not isinstance(req, list)
                                    or not all(isinstance(x, str) for x in req)):
                raise ValueError(f"kinds.{kid}: required must be a list of strings")

    # keep engine kind defaults in sync with stored kinds: add new inputs/text
    # that newer engine versions introduced, keep default required lists
    merged = {}
    for kid, base in DEFAULT_KINDS.items():
        cur = kinds.get(kid) if isinstance(kinds, dict) else None
        cur = cur if isinstance(cur, dict) else {}
        inputs = list(cur.get("inputs", base.get("inputs", [])))
        for i in base.get("inputs", []):
            if i not in inputs:
                inputs.append(i)
        text = list(cur.get("text", base.get("text", [])))
        for t in base.get("text", []):
            if t not in text:
                text.append(t)
        variants = cur.get("variants", base.get("variants"))
        merged[kid] = {
            "label": cur.get("label", base["label"]),
            "text": text,
            "inputs": inputs,
            "required": list(base.get("required", [])),
        }
        if variants:
            merged[kid]["variants"] = variants
        for extra in ("list", "colors", "rich"):
            val = cur.get(extra, base.get(extra))
            if val:
                merged[kid][extra] = val
    if isinstance(kinds, dict):
        for kid, defn in kinds.items():
            if kid not in merged:
                merged[kid] = defn
    d["kinds"] = merged
    kinds = merged

    deploy = d.get("deploy", {})
    if not isinstance(deploy, dict):
        raise ValueError("deploy must be an object")
    if deploy.get("provider", "") not in PROVIDERS:
        raise ValueError(f"deploy: bad provider '{deploy.get('provider')}'")
    for k in DEPLOY_KEYS[1:]:
        if not isinstance(deploy.get(k, ""), str):
            raise ValueError(f"deploy: {k} must be a string")

    pages = d.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages must be a non-empty list")
    seen = set()
    has_info = False
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            raise ValueError(f"pages[{i}]: must be an object")
        pid = p.get("id", "")
        label = p.get("label", "")
        ptype = p.get("type", "")
        if isinstance(pid, str) and pid.isalnum() and pid not in seen:
            seen.add(pid)
        else:
            raise ValueError(f"pages[{i}]: bad/duplicate id '{pid}'")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"pages[{i}]: label required")
        if ptype not in PAGE_TYPES:
            raise ValueError(f"pages[{i}]: bad type '{ptype}'")
        if ptype == "info":
            if pid != "info":
                raise ValueError("info page must have id 'info'")
            has_info = True
        else:
            _check_items(d.get(pid, []), pid, kinds)
    if not has_info:
        raise ValueError("at least one info page required")

    bio = d.get("bio", [])
    if not isinstance(bio, list) or not all(isinstance(x, str) for x in bio):
        raise ValueError("bio must be a list of strings")
    return d


def sanitize_filename(name, fallback="upload"):
    name = os.path.basename(name).strip().replace(" ", "_")
    safe = "".join(c for c in name if c.isalnum() or c in "._-")
    if not safe:
        safe = fallback
    ext = pathlib.Path(safe).suffix.lower()
    if ext in {".mp4"}:
        pass
    return safe


# ---- publish ----------------------------------------------------------------

PUBLISH_LOCK = threading.Lock()
BUILD_LOCK = threading.Lock()
P_STATES = {}


def pstate(slug):
    if slug not in P_STATES:
        P_STATES[slug] = {"running": False, "exit_code": None, "started": None,
                          "finished": None, "last_line": 0}
    return P_STATES[slug]


def render_site(inst):
    """Rebuild index.html from the instance's data + template (no-op while publishing)."""
    if pstate(inst["slug"])["running"] or not BUILD_LOCK.acquire(blocking=False):
        return False
    try:
        d = json.loads(inst["data"].read_text(encoding="utf-8"))
        template = build.TEMPLATE.read_text(encoding="utf-8")
        html = build.build(d, template, out_dir=inst["site"]) + "\n"
        (inst["site"] / "index.html").write_text(html, encoding="utf-8")
        return True
    except Exception:
        return False
    finally:
        BUILD_LOCK.release()


def read_history(inst):
    runs = _read_json(inst["history"], [])
    return runs if isinstance(runs, list) else []


def record_history(inst, provider, project, exit_code, started, finished):
    runs = read_history(inst)
    runs.append({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "provider": provider,
        "project": project,
        "ok": exit_code == 0,
        "seconds": round(finished - started, 1),
    })
    runs = runs[-50:]
    inst["history"].parent.mkdir(parents=True, exist_ok=True)
    inst["history"].write_text(json.dumps(runs, indent=2, ensure_ascii=False),
                               encoding="utf-8")


def run_publish(inst):
    st = pstate(inst["slug"])
    dep = (_read_json(inst["data"], {}) or {}).get("deploy", {}) if inst["data"].exists() else {}
    provider = dep.get("provider", "?")
    project = dep.get("project_name", "")
    if not PUBLISH_SH.exists() or not inst["secrets"].exists():
        st.update(running=False, exit_code=1, finished=time.time(), last_line=0)
        started = time.time()
        inst["log"].parent.mkdir(parents=True, exist_ok=True)
        inst["log"].write_text(
            "publish.sh or secrets.env missing (see registry / create the file)\n",
            encoding="utf-8")
        record_history(inst, provider, project, 1, started, time.time())
        return
    # Pre-validate (same logic as publish.sh head — fail-fast, write log)
    try:
        errors = validate_deploy(inst)
        if errors:
            st.update(running=False, exit_code=1, finished=time.time(), last_line=0)
            started = time.time()
            inst["log"].parent.mkdir(parents=True, exist_ok=True)
            lines = [
                "========================================",
                f"SITE : {inst['slug']}",
                f"DATA : {inst['data']}",
                f"SECR : {inst['secrets']}",
                f"PROV : {provider}",
                "========================================",
                "",
                "Publish can't start yet:",
            ] + [f" • {e}" for e in errors] + [
                "",
                f"Fix: http://{HOST}:{PORT}/admin  →  switch to site '{inst['slug']}'  →  Deploy tab",
                "fill in the fields above, press Save deploy config, then Publish.",
            ]
            inst["log"].write_text("\n".join(lines) + "\n", encoding="utf-8")
            record_history(inst, provider, project, 1, started, time.time())
            return
    except Exception:
        pass  # if validation itself fails, let bash run anyway
    st.update(running=True, exit_code=None, started=time.time(), finished=None, last_line=0)
    started = time.time()
    inst["log"].parent.mkdir(parents=True, exist_ok=True)
    inst["log"].write_text("", encoding="utf-8")
    try:
        proc = subprocess.run(["bash", str(PUBLISH_SH), inst["slug"]],
                              capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        output = (proc.stdout or "") + (proc.stderr or "")
        with inst["log"].open("a", encoding="utf-8") as f:
            f.write(output)
            if not output.endswith("\n"):
                f.write("\n")
        st.update(exit_code=proc.returncode)
    except Exception as e:  # noqa: BLE001
        with inst["log"].open("a", encoding="utf-8") as f:
            f.write(f"publish failed: {e}\n")
        st.update(exit_code=1)
    finally:
        st.update(running=False, finished=time.time())
        code = st.get("exit_code")
        if code is None:
            code = 1
        record_history(inst, provider, project, code, started, time.time())


def publish_status(inst):
    st = dict(pstate(inst["slug"]))
    log = ""
    if inst["log"].exists():
        lines = inst["log"].read_text(encoding="utf-8").splitlines()
        st["last_line"] = min(st.get("last_line", 0), len(lines))
        log = "\n".join(lines[st["last_line"]:])
        st["last_line"] = len(lines)
        st["log"] = log
    st["path"] = str(inst["site"])
    return st


# ---- rate limiter ------------------------------------------------------------

login_times = {}
login_lock = threading.Lock()


def rate_allowed(ip):
    now = time.time()
    with login_lock:
        entry = login_times.get(ip)
        if entry and entry.get("blocked_until", 0) > now:
            return False, entry["blocked_until"]
        tries = [t for t in entry.get("tries", []) if t > now - RATE_WINDOW] if entry else []
        if len(tries) >= RATE_MAX:
            blocked = now + RATE_BACKOFF
            login_times[ip] = {"tries": tries, "blocked_until": blocked}
            return False, blocked
        return True, None


def rate_note(ip):
    with login_lock:
        entry = login_times.setdefault(ip, {"tries": [], "blocked_until": 0})
        entry["tries"] = [t for t in entry["tries"] if t > time.time() - RATE_WINDOW]
        entry["tries"].append(time.time())


# ---- HTTP handler --------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SlutAdmin/1.0"

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise ValueError("body too large")
        return self.rfile.read(length) if length else b""

    def _client_ip(self):
        return self.client_address[0]

    def _auth(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return check_token(auth[7:])
        return None

    def _inst(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return instance_paths(q.get("site", [""])[0].strip())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PUT(self):
        self.do_POST()

    def do_DELETE(self):
        self.do_POST()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        inst = self._inst()
        if path.startswith("/admin/api/status"):
            self._json(200, publish_status(inst))
        elif path == "/admin/api/siteinfo":
            d = _read_json(inst["data"], None)
            self._json(200, {"name": (d or {}).get("site", {}).get("name", "site")})
        elif path == "/admin/api/sites":
            user = self._auth()
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"default": default_slug(), "sites": list_instances()})
        elif path == "/admin/api/data":
            user = self._auth()
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            d = _read_json(inst["data"], None)
            if d is None:
                self._json(500, {"error": "data.json unreadable"})
                return
            self._json(200, d)
        elif path == "/admin/api/media":
            user = self._auth()
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            try:
                files = [p.name for p in inst["site"].iterdir()
                         if p.is_file() and p.suffix.lower() in MEDIA_EXT]
            except OSError:
                files = []
            self._json(200, {"files": sorted(files)})
        elif path == "/admin/api/file":
            # public on localhost: <img>/<video> previews can't send the auth header
            q = urllib.parse.urlsplit(self.path)
            name = os.path.basename(urllib.parse.parse_qs(q.query).get("name", [""])[0])
            file = (inst["site"] / name).resolve()
            if not file.is_file() or not str(file).startswith(str(inst["site"].resolve())):
                self._json(404, {"error": "not found"})
                return
            self._send(200, file.read_bytes(), MIME.get(file.suffix.lower(), "application/octet-stream"))
        elif path == "/preview" or path.startswith("/preview/"):
            # local preview of the built site, always rebuilt from that instance's data.
            # /preview/<slug>/<rest> so relative media resolve inside the right folder.
            # ?edit=1 renders in visual-editor mode in memory (never written to disk).
            edit_q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("edit", [""])[0]
            edit_mode = bool(edit_q)
            rest = path.removeprefix("/preview").lstrip("/")
            if rest:
                parts = rest.split("/", 1)
                slug = parts[0]
                rel = parts[1] if len(parts) > 1 else ""
                inst = instance_paths(slug)
                if inst is None:
                    self._json(404, {"error": "site not found"})
                    return
            else:
                inst = self._inst()
                rel = ""
            if edit_mode and rel in ("", "index.html"):
                try:
                    d = json.loads(inst["data"].read_text(encoding="utf-8"))
                    template = build.TEMPLATE.read_text(encoding="utf-8")
                    html = build.build(d, template, out_dir=inst["site"], edit=True)
                except Exception:
                    self._json(500, {"error": "edit render failed"})
                    return
                self._send(200, (html + "\n").encode("utf-8"), "text/html")
                return
            render_site(inst)
            file = (inst["site"] / (rel or "index.html")).resolve()
            if file.is_dir():
                file = (file / "index.html").resolve()
            if not file.is_file() or not str(file).startswith(str(inst["site"].resolve())):
                self._json(404, {"error": "not found"})
                return
            self._send(200, file.read_bytes(),
                       "text/html" if file.suffix == ".html" else
                       MIME.get(file.suffix.lower(), "application/octet-stream"))
        elif path.startswith("/admin/static/"):
            rel = path.removeprefix("/admin/static/")
            file = (STATIC / rel).resolve()
            if not str(file).startswith(str(STATIC.resolve())):
                self._json(403, {"error": "forbidden"})
                return
            if file.is_file():
                self._send(200, file.read_bytes(),
                           "text/html" if rel.endswith(".html") else
                           "text/css" if rel.endswith(".css") else
                           "application/javascript" if rel.endswith(".js") else
                           "application/octet-stream")
            else:
                self._json(404, {"error": "not found"})
        elif path == "/admin/api/deploy":
            user = self._auth()
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            d = _read_json(inst["data"], {}) or {}
            cfg = {k: d.get("deploy", {}).get(k, "") for k in DEPLOY_KEYS}
            env = read_secrets_env(inst["secrets"])
            creds = {p: bool(env.get(PROVIDER_SECRET[p])) for p in PROVIDERS}
            self._json(200, {"config": cfg, "creds": creds,
                             "providers": PROVIDERS,
                             "site": inst["slug"]})
        elif path == "/admin/api/history":
            user = self._auth()
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"runs": read_history(inst)})
        elif path == "/admin/api/export":
            user = self._auth()
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            body = inst["data"].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="data.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/admin":
            self.send_response(302)
            self.send_header("Location", "/admin/static/admin.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path.startswith("/admin/"):
            self._json(404, {"error": "not found"})
        else:
            # serve the site folder at root so relative media resolve like in prod
            raw = urllib.parse.urlsplit(self.path).path.lstrip("/")
            file = (inst["site"] / (raw or "index.html")).resolve()
            if not str(file).startswith(str(inst["site"].resolve())):
                self._json(404, {"error": "not found"})
                return
            if file.is_dir():
                file = (file / "index.html").resolve()
            if not file.is_file():
                self._json(404, {"error": "not found"})
                return
            self._send(200, file.read_bytes(),
                       "text/html" if file.suffix == ".html" else
                       MIME.get(file.suffix.lower(), "application/octet-stream"))

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/admin/api/login":
            self._login()
            return
        user = self._auth()
        if not user:
            self._json(401, {"error": "unauthorized"})
            return
        inst = self._inst()
        if path == "/admin/api/data":
            self._save_data(inst)
        elif path == "/admin/api/upload":
            self._upload(inst)
        elif path == "/admin/api/build":
            self._build(inst)
        elif path == "/admin/api/publish":
            if PUBLISH_LOCK.acquire(blocking=False):
                threading.Thread(target=self._publish_worker, args=(inst,),
                                 daemon=True).start()
                self._json(202, {"ok": True})
            else:
                self._json(409, {"error": "publish already running"})
        elif path == "/admin/api/import":
            try:
                d = validate_data(json.loads(self._body() or b"{}"))
            except (ValueError, UnicodeDecodeError) as e:
                self._json(400, {"error": str(e)})
                return
            inst["data"].parent.mkdir(parents=True, exist_ok=True)
            inst["data"].write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
            render_site(inst)
            self._json(200, {"ok": True})
        elif path == "/admin/api/password":
            self._change_password(user)
        elif path == "/admin/api/sites":
            self._create_site()
        elif path == "/admin/api/media" and self.command == "DELETE":
            q = urllib.parse.urlsplit(self.path)
            name = os.path.basename(urllib.parse.parse_qs(q.query).get("name", [""])[0])
            site = inst["site"]
            file = (site / name).resolve()
            if (not name or not file.is_file()
                    or not str(file).startswith(str(site.resolve()))
                    or file.suffix.lower() not in MEDIA_EXT):
                self._json(404, {"error": "not found"})
                return
            file.unlink()
            self._json(200, {"ok": True})
        elif path == "/admin/api/deploy":
            self._deploy_save(inst)
        else:
            self._json(404, {"error": "not found"})

    def _deploy_save(self, inst):
        """Save deploy config (data.json) + per-provider API tokens (secrets.env)."""
        try:
            body = json.loads(self._body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "bad request"})
            return
        dep = body.get("deploy", {}) if isinstance(body.get("deploy"), dict) else {}
        if dep.get("provider", "") not in PROVIDERS:
            self._json(400, {"error": "deploy: bad provider"})
            return
        for k in DEPLOY_KEYS[1:]:
            if not isinstance(dep.get(k, ""), str):
                self._json(400, {"error": f"deploy: {k} must be a string"})
                return
        try:
            d = json.loads(inst["data"].read_text(encoding="utf-8"))
        except (ValueError, OSError):
            self._json(500, {"error": "cannot read data.json"})
            return
        d["deploy"] = {k: (dep.get(k) or "") for k in DEPLOY_KEYS}
        inst["data"].write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

        creds = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        env = read_secrets_env(inst["secrets"])
        added = 0
        for p in PROVIDERS:
            tok = creds.get(p)
            if isinstance(tok, str) and tok.strip():
                env[PROVIDER_SECRET[p]] = tok.strip()
                added += 1
        if added:
            write_secrets_env(inst["secrets"], env)
        self._json(200, {"ok": True})

    def _publish_worker(self, inst):
        try:
            run_publish(inst)
        finally:
            PUBLISH_LOCK.release()

    def _login(self):
        ok, until = rate_allowed(self._client_ip())
        if not ok:
            self._json(429, {"error": "too many attempts", "retry_in": int(until - time.time())})
            return
        try:
            body = json.loads(self._body() or b"{}")
            username = str(body.get("username", ""))
            password = str(body.get("password", ""))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "bad request"})
            return
        rate_note(self._client_ip())
        if verify_user(username, password):
            self._json(200, {"ok": True, "token": make_token(username), "user": username})
        else:
            self._json(401, {"error": "wrong credentials"})

    def _change_password(self, user):
        try:
            body = json.loads(self._body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "bad request"})
            return
        current_pw = str(body.get("current_password", ""))
        new_pw = str(body.get("new_password", ""))
        if not verify_user(user, current_pw):
            self._json(403, {"error": "current password is wrong"})
            return
        if len(new_pw) < 8:
            self._json(400, {"error": "new password must be at least 8 characters"})
            return
        change_password(user, new_pw)
        self._json(200, {"ok": True})

    def _save_data(self, inst):
        try:
            d = validate_data(json.loads(self._body() or b"{}"))
        except (ValueError, UnicodeDecodeError) as e:
            self._json(400, {"error": str(e)})
            return
        inst["data"].parent.mkdir(parents=True, exist_ok=True)
        inst["data"].write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        inst["site"].mkdir(parents=True, exist_ok=True)
        render_site(inst)
        self._json(200, {"ok": True})

    def _build(self, inst):
        try:
            # In-process, never a `python3 build.py` subprocess: the packaged
            # desktop app runs this module inside the frozen interpreter and has
            # no python3 on PATH, so shelling out breaks the Build button.
            # The module is reloaded so the button always reflects the engine
            # files currently on disk rather than the ones read at startup.
            import importlib
            importlib.reload(build)
            d = json.loads(inst["data"].read_text(encoding="utf-8"))
            template = build.TEMPLATE.read_text(encoding="utf-8")
            html = build.build(d, template, out_dir=inst["site"]) + "\n"
            inst["site"].mkdir(parents=True, exist_ok=True)
            (inst["site"] / "index.html").write_text(html, encoding="utf-8")
            self._json(200, {"ok": True, "output": "ok"})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"ok": False, "output": f"build failed: {e}"})

    def _upload(self, inst):
        q = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(q.query)
        name = sanitize_filename(params.get("filename", [""])[0])
        ext = pathlib.Path(name).suffix.lower()
        if ext not in MEDIA_EXT:
            self._json(400, {"error": f"unsupported type '{ext}', allowed: "
                                      + ", ".join(sorted(MEDIA_EXT))})
            return
        try:
            data = self._body()
        except ValueError as e:
            self._json(413, {"error": str(e)})
            return
        if not data:
            self._json(400, {"error": "empty body"})
            return
        site = inst["site"]
        dest = (site / name).resolve()
        if not str(dest).startswith(str(site.resolve())):
            self._json(403, {"error": "forbidden"})
            return
        site.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self._json(200, {"ok": True, "name": name, "url": name})

    def _create_site(self):
        """POST /admin/api/sites {slug, title} -> scaffold sites/<slug>/ + registry entry."""
        try:
            body = json.loads(self._body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "bad request"})
            return
        slug = str(body.get("slug", "")).strip().lower()
        title = str(body.get("title", "")).strip()
        if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
            self._json(400, {"error": "slug must match [a-z0-9][a-z0-9_-]*"})
            return
        reserved = {"default", "admin", "static", "sites", "reference", "media",
                    "template", "engine", "build", "slut"}
        if slug in reserved or slug in read_registry().get("sites", {}):
            self._json(400, {"error": "slug is taken or reserved"})
            return
        slug_dir = (ROOT / "sites" / slug).resolve()
        if not str(slug_dir).startswith(str(ROOT.resolve())):
            self._json(403, {"error": "forbidden"})
            return
        slug_dir.mkdir(parents=True, exist_ok=True)
        data_path = slug_dir / "data.json"
        if not data_path.exists():
            starter = _starter_data(title or slug)
            data_path.write_text(json.dumps(starter, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        secrets_path = slug_dir / "secrets.env"
        if not secrets_path.exists():
            secrets_path.write_text("", encoding="utf-8")
            try:
                os.chmod(secrets_path, 0o600)
            except OSError:
                pass
        reg = read_registry()
        reg.setdefault("sites", {})[slug] = {
            "title": title or slug,
            "data": f"sites/{slug}/data.json",
            "site": f"sites/{slug}/public",
            "secrets": f"sites/{slug}/secrets.env",
            "log": f"sites/{slug}/publish.log",
            "history": f"sites/{slug}/deploy_history.json",
        }
        write_registry(reg)
        self._json(200, {"ok": True, "slug": slug})


def main():
    os.makedirs(STATIC, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"admin on http://{HOST}:{PORT}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()