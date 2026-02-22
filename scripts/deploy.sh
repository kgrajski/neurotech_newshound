#!/usr/bin/env bash
#
# Deploy workspace to OpenClaw droplet.
#
# Usage:
#   bash scripts/deploy.sh
#
# This script:
#   1. Rsyncs workspace/ to ~/.openclaw/workspace/ on the droplet
#   2. Pushes API keys from local .env to the skill directory
#   3. Installs Python dependencies
#
# After deploying, trigger the agent from Telegram or the OpenClaw dashboard.
# Then run: bash scripts/fetch_reports.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [[ -f "$PROJECT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
else
    echo "ERROR: No .env file found. Copy .env.example to .env and fill in your keys."
    exit 1
fi

DROPLET_HOST="${DROPLET_HOST:?Set DROPLET_HOST in .env (e.g., 123.45.67.89)}"
DROPLET_USER="${DROPLET_USER:-root}"
REMOTE_WORKSPACE="${REMOTE_WORKSPACE:-/root/.openclaw/workspace}"
REMOTE_SKILL="${REMOTE_WORKSPACE}/skills/neuro_hound"

echo "============================================================"
echo "NeuroTech NewsHound — Deploy to OpenClaw"
echo "============================================================"
echo "  Droplet: ${DROPLET_USER}@${DROPLET_HOST}"
echo ""

# ── Step 1: Sync code ────────────────────────────────────────────────
echo "=== [1/3] Syncing workspace ==="
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'archives/' \
    --exclude 'sources.json' \
    --exclude 'seen_items.json' \
    --exclude 'mlruns/' \
    --exclude '.env' \
    --exclude 'backfill_log.txt' \
    "${PROJECT_DIR}/workspace/" \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_WORKSPACE}/"
echo ""

# ── Step 2: Push API keys ────────────────────────────────────────────
echo "=== [2/3] Pushing API keys ==="
ENV_CONTENT=""
[[ -n "${OPENAI_API_KEY:-}" ]]  && ENV_CONTENT+="OPENAI_API_KEY=${OPENAI_API_KEY}\n"
[[ -n "${TAVILY_API_KEY:-}" ]]  && ENV_CONTENT+="TAVILY_API_KEY=${TAVILY_API_KEY}\n"
[[ -n "${GOOGLE_API_KEY:-}" ]]  && ENV_CONTENT+="GOOGLE_API_KEY=${GOOGLE_API_KEY}\n"
[[ -n "${NOTIFY_PHONE:-}" ]]    && ENV_CONTENT+="NOTIFY_PHONE=${NOTIFY_PHONE}\n"

ssh "${DROPLET_USER}@${DROPLET_HOST}" \
    "printf '${ENV_CONTENT}' > ${REMOTE_SKILL}/.env"
echo "  API keys deployed"
echo ""

# ── Step 3: Install dependencies ─────────────────────────────────────
echo "=== [3/3] Installing dependencies ==="
ssh "${DROPLET_USER}@${DROPLET_HOST}" "\
    if ! python3 -m pip --version >/dev/null 2>&1; then \
        echo '  Installing pip...' && \
        (apt-get update -qq && apt-get install -y -qq python3-pip python3-venv >/dev/null 2>&1 \
         || curl -sS https://bootstrap.pypa.io/get-pip.py | python3); \
    fi && \
    cd ${REMOTE_SKILL} && python3 -m pip install --break-system-packages -r requirements.txt 2>&1 | tail -5"

echo ""
echo "============================================================"
echo "Deploy complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Trigger the agent from Telegram or OpenClaw dashboard"
echo "  2. After it finishes: bash scripts/fetch_reports.sh"
