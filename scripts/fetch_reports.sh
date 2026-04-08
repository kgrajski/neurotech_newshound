#!/usr/bin/env bash
#
# Fetch reports and archives from OpenClaw droplet back to local.
#
# Usage:
#   bash scripts/fetch_reports.sh              # fetch only
#   bash scripts/fetch_reports.sh --cleanup    # fetch, then remove dated reports from droplet
#
# Pulls archives/neurotech/ from the droplet into workspace/archives/neurotech/.
# Includes HTML reports, dashboard, markdown, JSON, and alert files.
#
# With --cleanup, dated report files (YYYY-MM-DD.*) are removed from the droplet
# after a successful fetch. Aggregate files (dashboard, discoveries, meta_actions,
# cron.log) and state files are kept.

set -euo pipefail

CLEANUP=false
for arg in "$@"; do
    case "$arg" in
        --cleanup) CLEANUP=true ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

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

REMOTE_SKILL="${REMOTE_WORKSPACE}/skills/neuro_hound"
LOCAL_SKILL="${PROJECT_DIR}/workspace/skills/neuro_hound"

mkdir -p "$LOCAL_ARCHIVES"

# Fetch reports and archives
rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_ARCHIVES}" \
    "${LOCAL_ARCHIVES}"

# Pull back evolving state files (meta-agent may have updated these on the droplet)
echo ""
echo "=== Syncing state files ==="
rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_SKILL}/vocabulary.yaml" \
    "${LOCAL_SKILL}/vocabulary.yaml"

rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_SKILL}/discovery_memory.json" \
    "${LOCAL_SKILL}/discovery_memory.json" 2>/dev/null || true

rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_SKILL}/sources.json" \
    "${LOCAL_SKILL}/sources.json" 2>/dev/null || true

rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_SKILL}/seen_items.json" \
    "${LOCAL_SKILL}/seen_items.json" 2>/dev/null || true

rsync -avz \
    "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_SKILL}/editorial_memory.json" \
    "${LOCAL_SKILL}/editorial_memory.json" 2>/dev/null || true

echo ""
echo "=== Fetch complete ==="

# Show what we got
REPORT_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.md" -not -name ".gitkeep" -not -path "*/backfill/*" 2>/dev/null | wc -l | tr -d ' ')
HTML_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.html" -not -name "dashboard.html" 2>/dev/null | wc -l | tr -d ' ')
ALERT_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.alerts.json" 2>/dev/null | wc -l | tr -d ' ')
JSON_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.full.json" 2>/dev/null | wc -l | tr -d ' ')
HAS_DASHBOARD="no"
[[ -f "${LOCAL_ARCHIVES}dashboard.html" ]] && HAS_DASHBOARD="yes"
HAS_META="no"
[[ -f "${LOCAL_ARCHIVES}meta_actions.yaml" ]] && HAS_META="yes"
HAS_DISCO="no"
[[ -f "${LOCAL_ARCHIVES}discoveries.yaml" ]] && HAS_DISCO="yes"
DIGEST_COUNT=$(find "$LOCAL_ARCHIVES" -name "*.weekly_digest.json" 2>/dev/null | wc -l | tr -d ' ')
HAS_MEMORY="no"
[[ -f "${LOCAL_SKILL}/discovery_memory.json" ]] && HAS_MEMORY="yes"
HAS_EDITORIAL="no"
[[ -f "${LOCAL_SKILL}/editorial_memory.json" ]] && HAS_EDITORIAL="yes"

echo "  Markdown reports:  ${REPORT_COUNT}"
echo "  HTML reports:      ${HTML_COUNT}"
echo "  Alert files:       ${ALERT_COUNT}"
echo "  Full JSON:         ${JSON_COUNT}"
echo "  Weekly digests:    ${DIGEST_COUNT}"
echo "  Dashboard:         ${HAS_DASHBOARD}"
echo "  Meta-agent trace:  ${HAS_META}"
echo "  Discoveries:       ${HAS_DISCO}"
echo "  Discovery memory:  ${HAS_MEMORY}"
echo "  Editorial memory:  ${HAS_EDITORIAL}"

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

# Cleanup: remove dated report files from the droplet (keeps aggregates + state)
if [[ "$CLEANUP" == "true" ]]; then
    echo ""
    echo "=== Cleaning up dated reports on droplet ==="
    ssh "${DROPLET_USER}@${DROPLET_HOST}" "\
        cd ${REMOTE_ARCHIVES} && \
        rm -f [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].* && \
        echo '  Dated reports removed from droplet'"

    OPENCLAW_REPORTS="/home/openclaw/.openclaw/workspace/skills/neurotech_reports"
    ssh "${DROPLET_USER}@${DROPLET_HOST}" "\
        cd ${OPENCLAW_REPORTS} 2>/dev/null && \
        rm -f [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].* && \
        echo '  Dated reports removed from OpenClaw workspace'" 2>/dev/null || true

    echo "  Aggregate files (dashboard, discoveries, meta_actions, cron.log) preserved"
fi
