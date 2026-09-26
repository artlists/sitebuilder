#!/usr/bin/env bash
# Build the static site for one instance (arg = slug, default = registry
# default) and deploy it via the provider configured in its data.json ->
# deploy. API keys are read from that instance's secrets.env.
set -euo pipefail
SLUG="${1:-}"
ADMIN="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${ADMIN}/.." && pwd)"
REG="${ADMIN}/sites.json"

SLUG_USE="${SLUG}"
i=0
while IFS= read -r line; do
  case $i in
    0) SLUG_USE="$line" ;;
    1) SITE_DIR="$line" ;;
    2) DATA_FILE="$line" ;;
    3) SECRETS_FILE="$line" ;;
  esac
  i=$((i + 1))
done < <(python3 - "${ROOT}" "${REG}" "${SLUG}" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
reg = json.load(open(sys.argv[2]))
sites = reg.get("sites", {})
name = sys.argv[3] if sys.argv[3] in sites else reg.get("default", "slutonline")
print(name)
ent = sites.get(name, {})
res = lambda r: (root / (r if r else "data.json"))
print(res(ent.get("site", "../slutonline")))
print(res(ent.get("data", "data.json")))
print(res(ent.get("secrets", "admin/secrets.env")))
PY
)

set -a
source "${SECRETS_FILE}" 2>/dev/null || true
set +a

i=0
while IFS= read -r line; do
  case $i in
    0) PROVIDER="$line" ;;
    1) PROJECT="$line" ;;
    2) DOMAIN="$line" ;;
    3) REPO="$line" ;;
  esac
  i=$((i + 1))
done < <(python3 - "${DATA_FILE}" <<'PY'
import json, sys
d = {}
cnf = {}
try:
    d = json.load(open(sys.argv[1]))
    cnf = d.get("deploy", {})
except Exception:
    pass
print(cnf.get("provider", "cloudflare_pages"))
print(cnf.get("project_name", ""))
print(cnf.get("domain", ""))
print(cnf.get("repo", ""))
PY
)

PROJECT="${PROJECT:-${PROJECT_NAME:-}}"

# ------------------------------------------------------------------
# FAIL-FAST VALIDATION (BEFORE build — user should wait 0s on errors)
# ------------------------------------------------------------------
ADMIN_URL="http://127.0.0.1:8899/admin"
DPATH="${ADMIN_URL} -> switch to site '${SLUG_USE}' -> Deploy tab"

header() { echo "========================================"; echo "SITE : ${SLUG_USE}"; echo "DATA : ${DATA_FILE}"; echo "SECR : ${SECRETS_FILE}"; echo "PROV : ${PROVIDER}"; echo "========================================"; }

need() { echo "error: ${PROVIDER}: $1" >&2; echo "  -> fix: ${DPATH}" >&2; echo "     then press Save deploy config, then Publish." >&2; exit 1; }

case "${PROVIDER}" in
  cloudflare_pages)
    [ -n "${CLOUDFLARE_API_TOKEN:-}" ] || need "CLOUDFLARE_API_TOKEN not set. In Deploy tab paste your Cloudflare API token (Account.Read + Pages.Edit scope) into the Token field and Save."
    [ -n "${PROJECT}" ] || need "project name empty. In Deploy tab -> Project field, enter the Cloudflare Pages project name exactly as on dash.cloudflare.com. Hint for this site: try '${SLUG_USE}' (this gives https://${SLUG_USE}.pages.dev)."
    ;;
  github_pages)
    [ -n "${GITHUB_TOKEN:-}" ] || need "GITHUB_TOKEN not set (Deploy tab -> Token, scope 'public_repo')."
    [ -n "${REPO}" ] || need "'repo' not set (Deploy tab -> Repo, format: user/repo)."
    ;;
  netlify)
    [ -n "${NETLIFY_TOKEN:-}" ] || need "NETLIFY_TOKEN not set (Deploy tab -> Token)."
    ;;
  surge)
    [ -n "${SURGE_TOKEN:-}" ] || need "SURGE_TOKEN not set (run: surge token, then paste in Deploy tab -> Token)."
    [ -n "${DOMAIN}" ] || need "domain not set (Deploy tab -> Domain, e.g. '${SLUG_USE}.surge.sh')."
    ;;
  neocities)
    [ -n "${NEOCITIES_TOKEN:-}" ] || need "NEOCITIES_TOKEN not set (Deploy tab -> Token -> Neocities API key)."
    ;;
  *)
    echo "error: unknown provider '${PROVIDER}'" >&2
    exit 1
    ;;
esac

mkdir -p "${SITE_DIR}"
cd "${ROOT}"

# Resolve wrangler if not set: prefer global, else npx cache
if [ "${PROVIDER}" = "cloudflare_pages" ] && [ -z "${WRANGLER_BIN:-}" ]; then
  if command -v wrangler >/dev/null 2>&1; then
    WRANGLER_BIN="wrangler"
  else
    WRANGLER_BIN="npx --yes wrangler"
  fi
fi

header
echo "building index.html..."
python3 build.py --data "${DATA_FILE}" --out "${SITE_DIR}/index.html"

cd "${SITE_DIR}"

fail() { echo "error: $*" >&2; exit 1; }

case "${PROVIDER}" in
  cloudflare_pages)
    echo "deploying to Cloudflare Pages project='${PROJECT}'..."
    # Ensure the project exists (create if missing).
    # We create via the REST API (not `wrangler pages project create`):
    # the CLI reads the wrong wrangler/vite config from the deploy dir and
    # fails; the API call is parameterised by project name only.
    rm -f wrangler.jsonc wrangler.toml 2>/dev/null || true
    CF_ACCT="$(curl -s -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
      "https://api.cloudflare.com/client/v4/accounts" \
      | python3 -c 'import json,sys;
r=json.load(sys.stdin)
print(r["result"][0]["id"] if r.get("result") else "")' 2>/dev/null || true)"
    if [ -n "${CF_ACCT}" ]; then
      curl -s -X POST \
        "https://api.cloudflare.com/client/v4/accounts/${CF_ACCT}/pages/projects" \
        -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
        -H "Content-Type: application/json" \
        --data "{\"name\":\"${PROJECT}\",\"production_branch\":\"main\"}" >/dev/null 2>&1 || true
    fi
    ${WRANGLER_BIN} pages deploy . \
      --project-name "${PROJECT}" \
      --commit-dirty=true
    ;;

  github_pages)
    echo "deploying to GitHub Pages repo='${REPO}'..."
    git init -q . 2>/dev/null || true
    git add -A
    git -c user.name="engine" -c user.email="engine@localhost" \
      commit -m "deploy $(date -u +%Y-%m-%dT%H:%M:%SZ)" --allow-empty -q
    git branch -M gh-pages
    git push -f "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" gh-pages
    ;;

  netlify)
    echo "deploying to Netlify${PROJECT:+ site='${PROJECT}'}..."
    netlify_cli="$(command -v netlify || echo "${NETLIFY_CLI:-}")"
    if [ -z "${netlify_cli}" ]; then
      echo "netlify-cli not installed locally — fetching via npx (may take a moment)"
    fi
    if [ -n "${PROJECT}" ]; then
      npx --yes netlify-cli deploy --dir . --site "${PROJECT}" --prod --auth "${NETLIFY_TOKEN}"
    else
      npx --yes netlify-cli deploy --dir . --prod --auth "${NETLIFY_TOKEN}"
    fi
    ;;

  surge)
    echo "deploying to Surge domain='${DOMAIN}'..."
    npx --yes surge . "${DOMAIN}" --token "${SURGE_TOKEN}"
    ;;

  neocities)
    echo "uploading to Neocities..."
    args=()
    while IFS= read -r -d '' f; do
      args+=(-F "${f#./}=@${f}")
    done < <(find "$(pwd)" -type f -print0)
    curl -sS -F "api_key=${NEOCITIES_TOKEN}" "${args[@]}" https://api.neocities.org/upload
    echo
    ;;

  *)
    fail "unknown provider: ${PROVIDER}"
    ;;
esac

if [ -n "${DOMAIN}" ]; then
  echo ""
  echo "✅  live at ${DOMAIN}"
else
  case "${PROVIDER}" in
    cloudflare_pages) echo ""; echo "✅  live at https://${PROJECT}.pages.dev" ;;
    surge)            echo ""; echo "✅  live at https://${DOMAIN}" ;;
  esac
fi
