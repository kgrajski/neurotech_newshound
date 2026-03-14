#!/usr/bin/env bash
#
# Cron wrapper: run the NeuroTech NewsHound nightly and send notifications.
#
# Installed on the droplet via: scripts/install_cron.sh
# Schedule: Every night at 05:00 UTC (midnight ET)
#
# On the configured weekly digest day (default: Saturday), the agent
# also produces a 7-day digest aggregating daily reports.

set -euo pipefail

SKILL_DIR="/root/.openclaw/workspace/skills/neuro_hound"
LOG_FILE="/root/.openclaw/workspace/archives/neurotech/cron.log"
ARCHIVE_DIR="/root/.openclaw/workspace/archives/neurotech"
TODAY=$(date -u '+%Y-%m-%d')
DAY_OF_WEEK=$(date -u '+%u')  # 1=Mon, 6=Sat, 7=Sun

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Starting NeuroTech NewsHound (daily)" >> "$LOG_FILE"

cd "$SKILL_DIR"

# Daily run with 2-day lookback (default from config.yaml)
if python3 -u run.py >> "$LOG_FILE" 2>&1; then
    STATUS="done"
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
    MSG="NeuroTech NewsHound daily briefing (${TODAY}): ${ALERT_COUNT} alerts, ${THEME_COUNT} themes."

    # Check if weekly digest was also produced (run.py auto-detects the day)
    DIGEST_FILE="${ARCHIVE_DIR}/${TODAY}.weekly_digest.json"
    if [[ -f "$DIGEST_FILE" ]]; then
        DIGEST_ITEMS=$(python3 -c "import json; d=json.load(open('${DIGEST_FILE}')); print(d.get('total_items',0))" 2>/dev/null || echo 0)
        DIGEST_ALERTS=$(python3 -c "import json; d=json.load(open('${DIGEST_FILE}')); print(d.get('total_alerts',0))" 2>/dev/null || echo 0)
        MSG="${MSG} Weekly digest: ${DIGEST_ITEMS} items, ${DIGEST_ALERTS} alerts."
    fi

    MSG="${MSG} Fetch with: bash scripts/fetch_reports.sh"
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
cp "$SKILL_DIR/discovery_memory.json" "$OPENCLAW_REPORTS/" 2>/dev/null || true
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
