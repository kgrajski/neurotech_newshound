#!/usr/bin/env bash
#
# Deploy workspace to OpenClaw droplet.
#
# Usage:
#   bash scripts/deploy.sh
#
# Reads DROPLET_HOST and DROPLET_USER from .env (or defaults to root@<ip>).
# Rsyncs the workspace/ directory to ~/.openclaw/workspace/ on the droplet.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if present
if [[ -f "$PROJECT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
fi

DROPLET_HOST="${DROPLET_HOST:?Set DROPLET_HOST in .env (e.g., 123.45.67.89)}"
DROPLET_USER="${DROPLET_USER:-root}"
REMOTE_WORKSPACE="${REMOTE_WORKSPACE:-/root/.openclaw/workspace}"

echo "=== Deploying to ${DROPLET_USER}@${DROPLET_HOST} ==="
echo "  Local:  ${PROJECT_DIR}/workspace/"
echo "  Remote: ${REMOTE_WORKSPACE}/"
echo ""

rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'archives/'  \
    "${PROJECT_DIR}/workspace/" \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_WORKSPACE}/"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "To test on droplet:"
echo "  ssh ${DROPLET_USER}@${DROPLET_HOST}"
echo "  cd ${REMOTE_WORKSPACE}"
echo "  python3 skills/neuro_hound/run.py --days 7"
