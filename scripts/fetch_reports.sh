#!/usr/bin/env bash
#
# Fetch reports and archives from OpenClaw droplet back to local.
#
# Usage:
#   bash scripts/fetch_reports.sh
#
# Pulls archives/neurotech/ from the droplet into workspace/archives/neurotech/.

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

LOCAL_ARCHIVES="${PROJECT_DIR}/workspace/archives/neurotech/"
REMOTE_ARCHIVES="${REMOTE_WORKSPACE}/archives/neurotech/"

echo "=== Fetching reports from ${DROPLET_USER}@${DROPLET_HOST} ==="
echo "  Remote: ${REMOTE_ARCHIVES}"
echo "  Local:  ${LOCAL_ARCHIVES}"
echo ""

mkdir -p "$LOCAL_ARCHIVES"

rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_ARCHIVES}" \
    "${LOCAL_ARCHIVES}"

echo ""
echo "=== Fetch complete ==="

# Show what we got
REPORT_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.md" -not -name ".gitkeep" | wc -l | tr -d ' ')
ALERT_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.alerts.json" | wc -l | tr -d ' ')
echo "  Reports: ${REPORT_COUNT}"
echo "  Alert files: ${ALERT_COUNT}"

# Show most recent
LATEST=$(find "$LOCAL_ARCHIVES" -name "*.md" -not -name ".gitkeep" | sort -r | head -1)
if [[ -n "$LATEST" ]]; then
    echo "  Latest: $(basename "$LATEST")"
fi
