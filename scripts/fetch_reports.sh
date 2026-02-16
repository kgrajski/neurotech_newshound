#!/usr/bin/env bash
#
# Fetch reports and archives from OpenClaw droplet back to local.
#
# Usage:
#   bash scripts/fetch_reports.sh
#
# Pulls archives/neurotech/ from the droplet into workspace/archives/neurotech/.
# Includes HTML reports, dashboard, markdown, JSON, and alert files.

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
REPORT_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.md" -not -name ".gitkeep" 2>/dev/null | wc -l | tr -d ' ')
HTML_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.html" -not -name "dashboard.html" 2>/dev/null | wc -l | tr -d ' ')
ALERT_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.alerts.json" 2>/dev/null | wc -l | tr -d ' ')
JSON_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.full.json" 2>/dev/null | wc -l | tr -d ' ')
HAS_DASHBOARD="no"
[[ -f "${LOCAL_ARCHIVES}dashboard.html" ]] && HAS_DASHBOARD="yes"

echo "  Markdown reports: ${REPORT_COUNT}"
echo "  HTML reports:     ${HTML_COUNT}"
echo "  Alert files:      ${ALERT_COUNT}"
echo "  Full JSON:        ${JSON_COUNT}"
echo "  Dashboard:        ${HAS_DASHBOARD}"

# Show most recent and offer to open
LATEST=$(find "$LOCAL_ARCHIVES" -name "*.html" -not -name "dashboard.html" 2>/dev/null | sort -r | head -1)
if [[ -n "$LATEST" ]]; then
    echo ""
    echo "  Latest: $(basename "$LATEST")"
    echo ""
    echo "To view:"
    echo "  open \"${LATEST}\""
    [[ "$HAS_DASHBOARD" == "yes" ]] && echo "  open \"${LOCAL_ARCHIVES}dashboard.html\""
fi
