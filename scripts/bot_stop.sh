#!/bin/bash
# Stop the Telegram bot and re-enable normal sleep behavior
PID_FILE="/tmp/telegram_bot.pid"

# Stop bot
if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if kill -0 "$BOT_PID" 2>/dev/null; then
        echo "Stopping bot (PID $BOT_PID)..."
        kill "$BOT_PID"
        sleep 1
        # Force kill if still running
        kill -9 "$BOT_PID" 2>/dev/null
        echo "Bot stopped."
    else
        echo "Bot was not running (stale PID file)."
    fi
    rm -f "$PID_FILE"
else
    # Try to find by process name
    PIDS=$(pgrep -f "telegram_bot.py" 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "Stopping bot (PID $PIDS)..."
        kill $PIDS 2>/dev/null
        sleep 1
        kill -9 $PIDS 2>/dev/null
        echo "Bot stopped."
    else
        echo "Bot is not running."
    fi
fi

# Re-enable sleep/suspend
echo "Re-enabling sleep/suspend..."
sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || \
    systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || \
    echo "WARNING: Could not re-enable sleep (need sudo?)"

echo "Done. PC can sleep normally again."
