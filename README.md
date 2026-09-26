# SiteBuilder — one-click site constructor

A self-contained desktop app: download the release for your OS, double-click,
and the local constructor server starts. It builds a single-page site from
editable `data.json` and opens the admin UI in your browser.

## Install (one click)

| Platform | File | What it does |
|----------|------|--------------|
| Windows  | `SiteBuilder-Windows.exe` | Double-click → console opens, browser opens `http://127.0.0.1:8899/admin` |
| macOS    | `SiteBuilder-macOS.zip`  | Unzip → double-click `SiteBuilder.app` → browser opens the admin |

First run creates a workspace (`~/SiteBuilder`, or `%LOCALAPPDATA%\SiteBuilder`
on Windows), copies the engine + a clean starter `data.json`, and generates a
random admin password — saved to `ADMIN-CREDENTIALS.txt` in the workspace
and printed in the console.

The server is local-only (`127.0.0.1`), no account, no telemetry.

## What runs under the hood

- `app/launcher.py` — desktop entry point: workspace init, password seed,
  server start, browser open.
- `engine/` — the constructor engine:
  - `build.py` — builds `index.html` from `data.json` + `template.html`.
  - `admin/server.py` — local admin HTTP API (`127.0.0.1:8899`).
  - `admin/static/` — the admin UI (edit site, upload media, deploy).
- `starter/data.json` — clean template the user edits.

## Workspace layout

```
~/SiteBuilder/
├── data.json                  # your site content (edited in admin)
├── build.py  template.html    # engine
├── admin/                     # server + credentials + deploy state
│   ├── users.json             # admin user (PBKDF2 hash)
│   ├── ADMIN-CREDENTIALS.txt  # your generated login (workspace root)
│   └── sites.json             # instance registry
└── site/                      # built site output
```

## Deploying to the web

The Deploy tab in the admin UI writes the static site to Cloudflare Pages /
GitHub Pages / etc. It shells out to the project CLI, so a working
wrangler/gh/netlify CLI is required on the machine (see the Deploy tab hints).

## Development

```bash
pip install pyinstaller
pyinstaller app/sitebuilder.spec
```

Run from source without packaging:

```bash
python3 app/launcher.py
```

Env overrides: `SBWORKSPACE`, `SBHOST`, `SBPORT`.

## Building a release

Tag a commit; `.github/workflows/release.yml` builds Windows + macOS and
attaches artifacts to the GitHub Release.

```bash
git tag v0.1.0
git push origin v0.1.0
```