#!/bin/bash
# Start the Telegram bot and prevent PC from sleeping
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="/tmp/telegram_bot.log"
PID_FILE="/tmp/telegram_bot.pid"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Bot is already running (PID $(cat "$PID_FILE"))"
    echo "Use bot_stop.sh to stop it first."
    exit 1
fi

# Check token
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    # Try to load from .env file
    if [ -f "$PROJECT_DIR/.env" ]; then
        export $(grep TELEGRAM_BOT_TOKEN "$PROJECT_DIR/.env" | xargs)
    fi
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ERROR: Set TELEGRAM_BOT_TOKEN environment variable or add it to .env"
    echo "Get one from @BotFather on Telegram."
    exit 1
fi

# Prevent sleep/suspend
echo "Disabling sleep/suspend..."
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || \
    systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || \
    echo "WARNING: Could not disable sleep (need sudo?)"

# Start bot
echo "Starting Telegram bot..."
cd "$PROJECT_DIR"
TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
    .venv/bin/python scripts/telegram_bot.py > "$LOG_FILE" 2>&1 &
BOT_PID=$!
disown $BOT_PID
echo "$BOT_PID" > "$PID_FILE"

sleep 2
if kill -0 "$BOT_PID" 2>/dev/null; then
    echo "Bot started (PID $BOT_PID)"
    echo "Log: $LOG_FILE"
    echo "Stop with: ./scripts/bot_stop.sh"
else
    echo "ERROR: Bot crashed on startup. Check $LOG_FILE"
    cat "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
