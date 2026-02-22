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
ARCHIVE_DIR="/root/.openclaw/workspace/archives/neurotech"
TODAY=$(date -u '+%Y-%m-%d')

if python3 -u run.py --days 7 >> "$LOG_FILE" 2>&1; then
    STATUS="done"
    # Parse actual counts from the alerts and full JSON
    ALERT_COUNT=0
    THEME_COUNT=0
    ALERT_FILE="${ARCHIVE_DIR}/${TODAY}.alerts.json"
    FULL_FILE="${ARCHIVE_DIR}/${TODAY}.full.json"
    if [[ -f "$ALERT_FILE" ]]; then
        ALERT_COUNT=$(python3 -c "import json; d=json.load(open('${ALERT_FILE}')); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo 0)
    fi
    if [[ -f "$FULL_FILE" ]]; then
        THEME_COUNT=$(python3 -c "import json; d=json.load(open('${FULL_FILE}')); print(len(d.get('themes',[])) if isinstance(d,dict) else 0)" 2>/dev/null || echo 0)
    fi
    MSG="NeuroTech NewsHound briefing for ${TODAY} is ready. ${ALERT_COUNT} alerts, ${THEME_COUNT} themes. Fetch with: bash scripts/fetch_reports.sh"
else
    STATUS="failed"
    MSG="NeuroTech NewsHound run failed. Check cron.log on the droplet."
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Run ${STATUS}" >> "$LOG_FILE"

# Publish reports to OpenClaw agent workspace so the chat agent can read them
OPENCLAW_REPORTS="/home/openclaw/.openclaw/workspace/skills/neurotech_reports"
mkdir -p "$OPENCLAW_REPORTS"
cp -r "$ARCHIVE_DIR"/* "$OPENCLAW_REPORTS/" 2>/dev/null || true
cp "$SKILL_DIR/vocabulary.yaml" "$OPENCLAW_REPORTS/" 2>/dev/null || true
cp "$SKILL_DIR/config.yaml" "$OPENCLAW_REPORTS/" 2>/dev/null || true
chown -R openclaw:openclaw "$OPENCLAW_REPORTS" 2>/dev/null || true
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Published to OpenClaw workspace" >> "$LOG_FILE"

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
