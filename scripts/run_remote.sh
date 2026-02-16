#!/usr/bin/env bash
#
# Deploy, push API keys, run the agent on the OpenClaw droplet, and fetch results.
#
# Usage:
#   bash scripts/run_remote.sh                  # Full pipeline, 7-day lookback
#   bash scripts/run_remote.sh --days 3         # 3-day lookback
#   bash scripts/run_remote.sh --phase1-only    # Regex only (no LLM cost)
#   bash scripts/run_remote.sh --model gpt-4o   # Use a different model
#
# This script:
#   1. Rsyncs workspace/ to the droplet (code + config)
#   2. Pushes API keys from local .env to the droplet
#   3. Installs Python dependencies
#   4. Runs the agent
#   5. Fetches reports back to local workspace/archives/neurotech/

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

DROPLET_HOST="${DROPLET_HOST:?Set DROPLET_HOST in .env}"
DROPLET_USER="${DROPLET_USER:-root}"
REMOTE_WORKSPACE="${REMOTE_WORKSPACE:-/root/.openclaw/workspace}"
SKILL_DIR="skills/neuro_hound"
REMOTE_SKILL="${REMOTE_WORKSPACE}/${SKILL_DIR}"

echo "============================================================"
echo "NeuroTech NewsHound — Remote Run"
echo "============================================================"
echo "  Droplet: ${DROPLET_USER}@${DROPLET_HOST}"
echo "  Args:    ${*:-(defaults: --days 7)}"
echo ""

# ── Step 1: Deploy code ──────────────────────────────────────────────
echo "=== [1/5] Deploying code ==="
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'archives/' \
    --exclude 'sources.json' \
    --exclude 'seen_items.json' \
    --exclude 'mlruns/' \
    "${PROJECT_DIR}/workspace/" \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_WORKSPACE}/"
echo ""

# ── Step 2: Push API keys ────────────────────────────────────────────
echo "=== [2/5] Pushing API keys ==="
# Build a minimal .env with just the API keys (not droplet connection info)
ENV_CONTENT=""
[[ -n "${OPENAI_API_KEY:-}" ]]  && ENV_CONTENT+="OPENAI_API_KEY=${OPENAI_API_KEY}\n"
[[ -n "${TAVILY_API_KEY:-}" ]]  && ENV_CONTENT+="TAVILY_API_KEY=${TAVILY_API_KEY}\n"
[[ -n "${GOOGLE_API_KEY:-}" ]]  && ENV_CONTENT+="GOOGLE_API_KEY=${GOOGLE_API_KEY}\n"

ssh "${DROPLET_USER}@${DROPLET_HOST}" \
    "printf '${ENV_CONTENT}' > ${REMOTE_SKILL}/.env"
echo "  API keys deployed to ${REMOTE_SKILL}/.env"
echo ""

# ── Step 3: Install dependencies ─────────────────────────────────────
echo "=== [3/5] Installing dependencies ==="
ssh "${DROPLET_USER}@${DROPLET_HOST}" \
    "cd ${REMOTE_SKILL} && pip3 install -q -r requirements.txt 2>&1 | tail -3"
echo ""

# ── Step 4: Run the agent ────────────────────────────────────────────
echo "=== [4/5] Running agent ==="
ssh -t "${DROPLET_USER}@${DROPLET_HOST}" \
    "cd ${REMOTE_SKILL} && python3 -u run.py $*"
echo ""

# ── Step 5: Fetch results ────────────────────────────────────────────
echo "=== [5/5] Fetching results ==="
LOCAL_ARCHIVES="${PROJECT_DIR}/workspace/archives/neurotech/"
REMOTE_ARCHIVES="${REMOTE_WORKSPACE}/archives/neurotech/"

mkdir -p "$LOCAL_ARCHIVES"
rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_ARCHIVES}" \
    "${LOCAL_ARCHIVES}"

echo ""
echo "============================================================"
echo "Done! Reports in: ${LOCAL_ARCHIVES}"
echo "============================================================"

# Show latest
LATEST=$(find "$LOCAL_ARCHIVES" -name "*.html" -not -name "dashboard.html" 2>/dev/null | sort -r | head -1)
if [[ -n "$LATEST" ]]; then
    echo ""
    echo "  open \"${LATEST}\""
    [[ -f "${LOCAL_ARCHIVES}dashboard.html" ]] && echo "  open \"${LOCAL_ARCHIVES}dashboard.html\""
fi
