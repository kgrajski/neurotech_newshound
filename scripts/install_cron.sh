#!/usr/bin/env bash
#
# Install the weekly cron job on the OpenClaw droplet.
#
# Usage (from project root):
#   bash scripts/install_cron.sh
#
# Schedule: Every Saturday at 11:00 UTC (6am ET / 7am EDT)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [[ -f "$PROJECT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
fi

DROPLET_HOST="${DROPLET_HOST:?Set DROPLET_HOST in .env}"
DROPLET_USER="${DROPLET_USER:-root}"
REMOTE_WORKSPACE="${REMOTE_WORKSPACE:-/root/.openclaw/workspace}"
REMOTE_SKILL="${REMOTE_WORKSPACE}/skills/neuro_hound"

echo "=== Installing cron job on ${DROPLET_USER}@${DROPLET_HOST} ==="

# Push the cron wrapper script
scp "${SCRIPT_DIR}/cron_run.sh" "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_SKILL}/cron_run.sh"
ssh "${DROPLET_USER}@${DROPLET_HOST}" "chmod +x ${REMOTE_SKILL}/cron_run.sh"

# Install crontab entry (Saturday 11:00 UTC = 6am ET)
CRON_LINE="0 11 * * 6 ${REMOTE_SKILL}/cron_run.sh"

ssh "${DROPLET_USER}@${DROPLET_HOST}" "
    crontab -l 2>/dev/null | grep -v 'cron_run.sh' | crontab - 2>/dev/null || true
    (crontab -l 2>/dev/null; echo '${CRON_LINE}') | crontab -
    echo 'Crontab installed:'
    crontab -l
"

echo ""
echo "=== Cron job installed ==="
echo "  Schedule: Every Saturday at 11:00 UTC (6am ET)"
echo "  Script:   ${REMOTE_SKILL}/cron_run.sh"
echo "  Log:      ${REMOTE_WORKSPACE}/archives/neurotech/cron.log"
echo ""
echo "  Notifications sent to NOTIFY_PHONE from .env (WhatsApp + Telegram)"
