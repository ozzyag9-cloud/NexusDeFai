#!/usr/bin/env python3
"""
NEXUS AI — Telegram Setup Helper
Run this ONCE to get your Channel ID and Admin (user) ID.

Usage:
  python setup_telegram.py

Steps:
  1. Add @gainezis_bot as admin to your Telegram channel
  2. Send any message to the channel (e.g. "test")
  3. Message @gainezis_bot directly in a private chat (send /start)
  4. Run this script — it will print your IDs
  5. Paste them into your .env file
"""

import urllib.request
import json

TOKEN = "8566203991:AAFgYMkqa3HqXqMgQ2VcyHiFUz2kMbBnMc4"
BASE  = f"https://api.telegram.org/bot{TOKEN}"


def api(method):
    try:
        with urllib.request.urlopen(f"{BASE}/{method}", timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ✗ API error: {e}")
        return None


def main():
    print("\n╔══════════════════════════════════════╗")
    print("║  NEXUS AI — Telegram Setup Helper    ║")
    print("╚══════════════════════════════════════╝\n")

    # 1. Verify bot
    print("1. Verifying bot token...")
    me = api("getMe")
    if not me or not me.get("ok"):
        print("  ✗ Bot token invalid. Check TELEGRAM_BOT_TOKEN in .env")
        return
    bot = me["result"]
    print(f"  ✓ Bot verified: @{bot['username']} (ID: {bot['id']})\n")

    # 2. Fetch updates
    print("2. Fetching recent updates...")
    updates = api("getUpdates?limit=50&allowed_updates=[\"message\",\"channel_post\"]")

    if not updates or not updates.get("ok") or not updates["result"]:
        print("  ⚠  No updates found yet.\n")
        print("  → Make sure you have:")
        print("    a) Added @gainezis_bot as ADMIN to your channel")
        print("    b) Sent at least one message to the channel after adding the bot")
        print("    c) Sent /start to @gainezis_bot in a private chat")
        print("\n  Then run this script again.\n")
        return

    channel_ids = set()
    user_ids    = set()

    for update in updates["result"]:
        # Channel posts
        cp = update.get("channel_post", {})
        if cp:
            chat = cp.get("chat", {})
            if chat.get("type") == "channel":
                channel_ids.add((chat["id"], chat.get("title", "Unknown")))

        # Private messages (to find your user ID)
        msg = update.get("message", {})
        if msg:
            chat = msg.get("chat", {})
            frm  = msg.get("from", {})
            if chat.get("type") == "private":
                user_ids.add((frm.get("id"), frm.get("username", ""), frm.get("first_name", "")))

    print("\n══════════════════════════════════════")
    print("  RESULTS — Copy these into your .env")
    print("══════════════════════════════════════\n")

    if channel_ids:
        print("TELEGRAM_CHANNEL_ID values found:")
        for cid, title in channel_ids:
            print(f"  Channel: \"{title}\"")
            print(f"  → TELEGRAM_CHANNEL_ID={cid}\n")
    else:
        print("  No channel found yet.")
        print("  → Add bot as admin and send a message to your channel first.\n")

    if user_ids:
        print("TELEGRAM_ADMIN_ID values found:")
        for uid, uname, fname in user_ids:
            uname_str = f"@{uname}" if uname else fname
            print(f"  User: {uname_str}")
            print(f"  → TELEGRAM_ADMIN_ID={uid}\n")
    else:
        print("  No admin user found yet.")
        print("  → Send /start to @gainezis_bot in a private chat first.\n")

    print("══════════════════════════════════════")
    print("  Next steps:")
    print("  1. Paste the IDs above into your .env")
    print("  2. Run: python main.py --once")
    print("  3. Check your Telegram channel for the first signal!")
    print("══════════════════════════════════════\n")


if __name__ == "__main__":
    main()
