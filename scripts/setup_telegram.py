"""
scripts/setup_telegram.py

One-time Telegram session setup via interactive phone auth.
Run this ONCE before using the telegram_api fetcher.

The session file (telegram.session) will be saved in the project root
and reused on all subsequent runs — no re-auth needed.

Usage:
    python -m scripts.setup_telegram
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")

    if not api_id or not api_hash:
        logger.error(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env\n"
            "Get them at https://my.telegram.org/apps"
        )
        sys.exit(1)

    try:
        from telethon.sync import TelegramClient
    except ImportError:
        logger.error("telethon not installed. Run: pip install telethon")
        sys.exit(1)

    session_path = Path(__file__).parent.parent / "telegram.session"
    logger.info("Session will be saved to: %s", session_path)

    if not phone:
        phone = input("Enter your phone number (e.g. +79001234567): ").strip()

    client = TelegramClient(str(session_path.with_suffix("")), int(api_id), api_hash)
    client.connect()

    if not client.is_user_authorized():
        from telethon.errors import SessionPasswordNeededError

        client.send_code_request(phone)
        code = input("Enter the code you received in Telegram: ").strip()
        try:
            client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input("Enter your 2FA password: ").strip()
            if not password:
                logger.error("2FA password cannot be empty")
                client.disconnect()
                sys.exit(1)
            client.sign_in(password=password)

    me = client.get_me()
    logger.info("Authorized as: %s (id=%s)", me.username or me.first_name, me.id)

    # Quick smoke test — fetch 1 message from a known public channel
    logger.info("Smoke test: fetching 1 message from @durov ...")
    msgs = client.get_messages("durov", limit=1)
    if msgs:
        logger.info("OK — got message id=%s", msgs[0].id)
    else:
        logger.warning("No messages returned (channel may be empty or restricted)")

    client.disconnect()
    logger.info("Session saved. You can now run the ingestion pipeline.")


if __name__ == "__main__":
    main()
