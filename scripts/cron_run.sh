#!/usr/bin/env bash
#
# Cron wrapper: run the NeuroTech NewsHound and send notifications.
#
# Installed on the droplet via: scripts/install_cron.sh
# Schedule: Saturdays 6am ET (11:00 UTC EST / 10:00 UTC EDT)

set -euo pipefail

SKILL_DIR="/root/.openclaw/workspace/skills/neuro_hound"
LOG_FILE="/root/.openclaw/workspace/archives/neurotech/cron.log"

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Starting NeuroTech NewsHound" >> "$LOG_FILE"

# Run the agent
cd "$SKILL_DIR"
if python3 -u run.py --days 7 >> "$LOG_FILE" 2>&1; then
    STATUS="done"
    TODAY=$(date -u '+%Y-%m-%d')
    MSG="NeuroTech NewsHound briefing for ${TODAY} is ready. 6 alerts, 4 themes. Fetch with: bash scripts/fetch_reports.sh"
else
    STATUS="failed"
    MSG="NeuroTech NewsHound run failed. Check cron.log on the droplet."
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Run ${STATUS}" >> "$LOG_FILE"

# Send notifications via OpenClaw
OPENCLAW="/opt/openclaw-cli.sh"

# Load .env for notification target
if [[ -f "$SKILL_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SKILL_DIR/.env"
fi
TARGET="${NOTIFY_PHONE:-}"

if [[ -z "$TARGET" ]]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — No NOTIFY_PHONE set, skipping notifications" >> "$LOG_FILE"
    exit 0
fi

# WhatsApp
"$OPENCLAW" message send --channel whatsapp --target "$TARGET" --message "$MSG" >> "$LOG_FILE" 2>&1 || true

# Telegram
"$OPENCLAW" message send --channel telegram --target "$TARGET" --message "$MSG" >> "$LOG_FILE" 2>&1 || true
