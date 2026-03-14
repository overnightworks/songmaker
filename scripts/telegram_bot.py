#!/usr/bin/env python3
"""Telegram bot that lets Felix chat with Claude via Claude Code CLI (Max subscription).
Runs in the songmaker project dir so Claude can generate songs and send MP3s."""

import asyncio
import json
import os
import logging
import re
import shutil
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("claude-telegram")

# ── Config ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PROJECT_DIR = os.environ.get(
    "SONGMAKER_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
ALLOWED_USER_IDS: set[int] = set()
_allowed_env = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
if _allowed_env:
    ALLOWED_USER_IDS = {int(uid.strip()) for uid in _allowed_env.split(",")}

MODEL = os.environ.get("CLAUDE_MODEL", "opus")

# Find claude CLI binary
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "")
if not CLAUDE_BIN:
    for candidate in [
        shutil.which("claude"),
        os.path.expanduser(
            "~/.vscode/extensions/anthropic.claude-code-2.1.75-linux-x64"
            "/resources/native-binary/claude"
        ),
    ]:
        if candidate and os.path.isfile(candidate):
            CLAUDE_BIN = candidate
            break

# Per-user session IDs for conversation continuity
sessions: dict[int, str] = {}

SYSTEM_PROMPT = (
    "You are Claude, chatting with Felix (Flex0r) via Telegram. "
    "You have full access to the Songmaker project. "
    "When you generate a song, always mention the full output path so the bot "
    "can send the MP3 file. Keep responses concise — this is mobile chat. "
    "You can run songmaker CLI commands, edit lyrics, generate songs, etc."
)

# ── Claude via CLI ──────────────────────────────────────────────────────
async def ask_claude(message: str, session_id: str | None = None) -> tuple[str, str | None]:
    """Send message to Claude Code CLI, return (reply, session_id)."""
    cmd = [
        CLAUDE_BIN,
        "-p", message,
        "--model", MODEL,
        "--output-format", "json",
        "--append-system-prompt", SYSTEM_PROMPT,
        "--dangerously-skip-permissions",
    ]

    if session_id:
        cmd.extend(["--resume", session_id])

    log.info(f"Running Claude CLI: {message[:80]}...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=PROJECT_DIR,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error = stderr.decode().strip() or stdout.decode().strip()
        raise RuntimeError(f"Claude CLI error (rc={proc.returncode}): {error}")

    try:
        data = json.loads(stdout.decode())
        reply = data.get("result", stdout.decode())
        new_session = data.get("session_id")
    except json.JSONDecodeError:
        reply = stdout.decode().strip()
        new_session = None

    return reply, new_session


def find_audio_files(text: str) -> list[Path]:
    """Extract MP3/WAV file paths mentioned in Claude's response."""
    patterns = re.findall(r'[\w./_-]*(?:_output|output)/[\w./_-]+\.(?:mp3|wav)', text)
    files = []
    for p in patterns:
        # Try as absolute and relative to project dir
        for candidate in [Path(p), Path(PROJECT_DIR) / p]:
            if candidate.is_file():
                files.append(candidate)
                break
    return files


# ── Handlers ────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    if not ALLOWED_USER_IDS:
        ALLOWED_USER_IDS.add(uid)
        log.info(f"Registered user: {user.full_name} (ID: {uid})")
        await update.message.reply_text(
            f"Registered! Your Telegram ID is {uid}.\n"
            f"Set TELEGRAM_ALLOWED_USER_IDS={uid} to lock it down.\n\n"
            f"I can chat, generate songs, edit lyrics — full Songmaker access!"
        )
    elif uid in ALLOWED_USER_IDS:
        await update.message.reply_text(
            "Hey Felix! Send me anything. I can generate songs too — "
            "just say something like 'generate where is the love'."
        )
    else:
        await update.message.reply_text("Not authorized.")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USER_IDS:
        return
    sessions.pop(uid, None)
    await update.message.reply_text("Conversation cleared.")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MODEL
    uid = update.effective_user.id
    if uid not in ALLOWED_USER_IDS:
        return
    args = context.args
    if args:
        MODEL = args[0]
        await update.message.reply_text(f"Model switched to {MODEL}")
    else:
        await update.message.reply_text(f"Current model: {MODEL}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ALLOWED_USER_IDS and uid not in ALLOWED_USER_IDS:
        return

    text = update.message.text
    if not text:
        return

    await update.message.chat.send_action("typing")

    try:
        session_id = sessions.get(uid)
        reply, new_session = await ask_claude(text, session_id)
        if new_session:
            sessions[uid] = new_session

        # Send text reply (split if needed)
        if len(reply) > 4000:
            for i in range(0, len(reply), 4000):
                await update.message.reply_text(reply[i : i + 4000])
        else:
            await update.message.reply_text(reply)

        # Send any generated audio files
        audio_files = find_audio_files(reply)
        for audio_path in audio_files:
            log.info(f"Sending audio: {audio_path}")
            await update.message.chat.send_action("upload_document")
            with open(audio_path, "rb") as f:
                await update.message.reply_audio(
                    audio=f,
                    title=audio_path.stem,
                    filename=audio_path.name,
                )

    except Exception as e:
        log.error(f"Claude error: {e}")
        await update.message.reply_text(f"Error: {e}")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN environment variable!")
        print("Get one from @BotFather on Telegram.")
        return

    if not CLAUDE_BIN:
        print("Could not find 'claude' CLI binary!")
        print("Set CLAUDE_BIN=/path/to/claude or install Claude Code.")
        return

    log.info(f"Using Claude CLI: {CLAUDE_BIN}")
    log.info(f"Model: {MODEL}")
    log.info(f"Project dir: {PROJECT_DIR}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot started! Send /start in Telegram to register.")
    app.run_polling()


if __name__ == "__main__":
    main()
